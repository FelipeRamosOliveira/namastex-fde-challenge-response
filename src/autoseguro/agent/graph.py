"""Grafo LangGraph do atendimento.

    entrada -> decidir -> cotar | handoff | saida
    cotar   -> saida | handoff
    handoff -> saida
    saida   -> aguardar_humano (interrupt, se acabou de ir para humano) | END
    aguardar_humano -> saida -> END   (retomado por Command(resume=...) do operador)

- entrada: guardrail de PII (mascara e guarda originais no vault da conversa)
- decidir: extrai dados/intenções, pré-valida regras, escolhe o próximo passo;
           também trata eventos de sistema (nova tentativa de cotação em segundo plano)
- cotar:   ferramenta MCP `cotar`. Se a API estiver fora, NÃO vai direto para humano:
           avisa o lead, fica em `aguardando_cotacao` e pede nova tentativa em segundo plano
- handoff: registra na fila do vendedor com resumo mascarado
- saida:   guardrail de saída (PII + valores em R$ só da API) e evento de rastreio
- aguardar_humano: `interrupt()` pausa a conversa até o operador devolver ao bot ou encerrar

Estado persistido por conversa (thread_id = conversation_ref) no checkpointer.
"""

from __future__ import annotations

import operator
import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from autoseguro.agent import templates as T
from autoseguro.agent.extract import CAMPOS, Extractor, RuleExtractor
from autoseguro.agent.gateway import ToolGateway
from autoseguro.guardrails.output import check_output
from autoseguro.guardrails.pii import PiiVault, mask

Stage = Literal["novo", "coletando", "confirmando", "cotado", "aguardando_cotacao", "handoff", "encerrado"]
EVENTO_RETENTAR = "retentar_cotacao"


_MIDIA_PT = {"image": "imagem", "document": "documento", "audio": "audio", "video": "video"}


class AgentState(TypedDict, total=False):
    conversation_id: str
    incoming: dict[str, Any]  # {message_id, text, message_type}
    turn_text: str  # texto do turno já mascarado
    vault: dict[str, str]  # token -> valor original (só no checkpoint)
    slots: dict[str, Any]
    cep_prefixo: str | None
    awaiting: str | None
    stage: Stage
    acao: str
    reply: str
    reply_prefix: str
    ponte: bool
    planos_mostrados: bool
    quotes: list[dict[str, Any]]  # respostas OK da API (fonte dos valores permitidos)
    quote_atual: dict[str, Any] | None
    handoff: dict[str, Any] | None
    handoff_pendente: dict[str, Any] | None
    turnos_sem_progresso: int
    midia_count: int
    objecoes: int
    tentativas_fundo: int  # novas tentativas de cotação em segundo plano já feitas
    agendar_retry: float | None  # segundos até a próxima tentativa (lido pela fachada)
    stage_antes_handoff: str | None
    transcript: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]


def _event(state: AgentState, type_: str, **data: Any) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "conversation_id": state.get("conversation_id"),
        "message_id": (state.get("incoming") or {}).get("message_id"),
        "type": type_,
        **data,
    }


def build_graph(
    gateway: ToolGateway,
    extractor: Extractor | None = None,
    checkpointer: Any = None,
    max_turnos_sem_progresso: int = 6,
    hoje: Any = date.today,
    redator: Any = None,
    retry_delays: tuple[float, ...] = (5.0, 20.0, 60.0),
):
    extractor = extractor or RuleExtractor()
    planos_cache: dict[str, Any] = {}

    async def planos() -> list[dict[str, Any]]:
        if not planos_cache:
            try:
                planos_cache.update(await gateway.consultar_planos())
            except Exception:  # noqa: BLE001 - sem lista de planos, a pergunta sai em versão curta
                return []
        return planos_cache["planos"]

    # ------------------------------------------------------------------ entrada
    async def entrada(state: AgentState) -> dict[str, Any]:
        vault = PiiVault.from_dict(state.get("vault"))
        inc = state["incoming"]
        if inc.get("message_type") == "system":  # evento interno, não é mensagem do lead
            return {
                "turn_text": "",
                "reply": "",
                "reply_prefix": "",
                "handoff_pendente": None,
                "ponte": False,
                "agendar_retry": None,
                "events": [_event(state, "evento_sistema", evento=inc.get("text"))],
            }
        masked = mask(inc["text"], vault)
        upd: dict[str, Any] = {
            "turn_text": masked.text,
            "vault": vault.to_dict(),
            "reply": "",
            "reply_prefix": "",
            "handoff_pendente": None,
            "ponte": False,
            "agendar_retry": None,
            "transcript": [
                {
                    "role": "lead",
                    "text": masked.text,
                    "message_id": inc["message_id"],
                    "message_type": inc.get("message_type", "text"),
                }
            ],
            "events": [
                _event(
                    state,
                    "message_in",
                    text=masked.text,
                    pii_detectada=sorted({e.kind.value for e in masked.entities}),
                    message_type=inc.get("message_type", "text"),
                )
            ],
        }
        if not state.get("stage") or state.get("stage") == "encerrado":  # conversa nova (ou reaberta)
            upd.update(
                stage="novo",
                slots={},
                quotes=[],
                quote_atual=None,
                handoff=None,
                awaiting=None,
                turnos_sem_progresso=0,
                midia_count=0,
                objecoes=0,
                tentativas_fundo=0,
                planos_mostrados=False,
            )
        return upd

    # ------------------------------------------------------------------ decidir
    async def decidir(state: AgentState) -> dict[str, Any]:
        stage = state.get("stage", "novo")
        inc = state.get("incoming") or {}
        if inc.get("message_type") == "system":
            if inc.get("text") == EVENTO_RETENTAR and stage == "aguardando_cotacao":
                return {"acao": "cotar", "tentativas_fundo": state.get("tentativas_fundo", 0) + 1}
            return {"acao": "responder", "reply": ""}  # evento sem efeito: nada a dizer
        if stage == "handoff":
            return {"acao": "responder", "reply": T.POS_HANDOFF}

        hj = hoje()
        text = state["turn_text"]
        mtype = state.get("incoming", {}).get("message_type", "text")
        if mtype != "text" and not text.startswith("["):
            text = f"[{_MIDIA_PT.get(mtype, mtype)}] {text}"
        ex = await extractor.extract(text, state.get("awaiting"), hj)
        events = [
            _event(
                state,
                "extracao",
                slots={k: str(v) for k, v in ex.slots.items()},
                intents=sorted(ex.intents),
                fonte=ex.fonte,
            )
        ]

        def handoff(motivo: str, detalhe: str | None = None) -> dict[str, Any]:
            return {
                "acao": "handoff",
                "handoff_pendente": {"motivo": motivo, "detalhe": detalhe},
                "events": events,
            }

        # mídia: pede texto uma vez; na segunda, humano
        if "midia" in ex.intents:
            n = state.get("midia_count", 0) + 1
            if n >= 2:
                return {**handoff("midia"), "midia_count": n}
            aw = state.get("awaiting")
            ask = T.perguntar(aw, await planos()) if aw in CAMPOS else ""
            return {
                "acao": "responder",
                "reply": f"{T.PEDIR_TEXTO} {ask}".strip(),
                "midia_count": n,
                "events": events,
            }

        if "pedido_humano" in ex.intents:
            return handoff("pedido_humano")
        if "fora_de_escopo" in ex.intents:
            return handoff("fora_de_escopo")
        if stage == "aguardando_cotacao":  # a nova tentativa já está agendada; só tranquiliza o lead
            return {"acao": "responder", "reply": T.AINDA_TENTANDO, "events": events}

        # ---- incorpora dados novos
        slots = dict(state.get("slots") or {})
        novos: dict[str, Any] = {}
        for k, v in ex.slots.items():
            if k == "data_inicio":
                if v < hj:
                    continue
                v = v.isoformat()
            if slots.get(k) != v:
                novos[k] = v
        slots.update(novos)
        vault = PiiVault.from_dict(state.get("vault"))
        cep_orig = vault.reveal(slots["cep"]) if slots.get("cep") else None
        cep_prefixo = re.sub(r"\D", "", cep_orig)[:2] if cep_orig else None

        # ---- pré-validação das regras (sem gastar chamada na /quote)
        if {"idade", "veiculo_ano"} & novos.keys():
            try:
                pv = await gateway.pre_validar(idade=slots.get("idade"), veiculo_ano=slots.get("veiculo_ano"))
            except Exception as e:  # noqa: BLE001 - a /quote devolve 422 se a regra falhar
                events.append(_event(state, "pre_validacao_falhou", erro=type(e).__name__))
            else:
                events.append(_event(state, "pre_validacao", **pv))
                if not pv["ok"]:
                    return {**handoff("recusa_regra", pv["motivo"]), "slots": slots}

        progresso = bool(novos) or bool(ex.intents & {"aceite", "negacao", "pergunta_planos"})
        sem_prog = 0 if progresso else state.get("turnos_sem_progresso", 0) + 1
        # frase natural do redator só quando o lead perguntou algo ou falou fora do fluxo
        ponte = "?" in text or (not ex.slots and not (ex.intents - {"saudacao"}))
        base = {
            "slots": slots,
            "turnos_sem_progresso": sem_prog,
            "events": events,
            "cep_prefixo": cep_prefixo,
            "ponte": ponte,
        }

        def data_vencida() -> bool:
            di = slots.get("data_inicio")
            return bool(di) and date.fromisoformat(di) < hj

        def pedir_nova_data() -> dict[str, Any]:
            slots.pop("data_inicio", None)
            return {
                **base,
                "slots": slots,
                "acao": "responder",
                "stage": "coletando",
                "awaiting": "data_inicio",
                "reply": "A data de início que combinamos já passou. " + T.perguntar("data_inicio"),
            }

        if sem_prog >= max_turnos_sem_progresso:
            return {**handoff("sem_progresso"), "slots": slots}

        # ---- já cotado: fechar, trocar plano ou objeção
        if stage == "cotado":
            atual = (state.get("quote_atual") or {}).get("plano_id")
            if {"idade", "veiculo_ano", "cep", "data_inicio"} & novos.keys():
                # dado da cotação mudou: a cotação antiga não vale mais; confirma de novo
                return {
                    **base,
                    "acao": "responder",
                    "stage": "confirmando",
                    "awaiting": "confirmacao",
                    "quote_atual": None,
                    "reply": "Atualizei seus dados. " + T.confirmar(slots, cep_prefixo),
                }
            if data_vencida() and (("plano_id" in novos) or ex.intents & {"objecao_preco", "aceite"}):
                return pedir_nova_data()
            if "plano_id" in novos and novos["plano_id"] != atual:
                return {**base, "acao": "cotar"}
            if ex.intents & {"objecao_preco", "concorrente"}:
                n = state.get("objecoes", 0) + 1
                if n == 1 and atual != "essencial" and "concorrente" not in ex.intents:
                    slots["plano_id"] = "essencial"
                    return {
                        **base,
                        "slots": slots,
                        "objecoes": n,
                        "acao": "cotar",
                        "reply_prefix": "Entendo. Uma opção mais em conta é o plano Essencial.\n",
                    }
                return {**handoff("objecao_preco"), "slots": slots, "objecoes": n}
            if "aceite" in ex.intents:
                return {**handoff("pronto_para_fechar"), "slots": slots}
            if "pergunta_planos" in ex.intents:
                return {**base, "acao": "responder", "reply": T.perguntar("plano_id", await planos())}
            return {
                **base,
                "acao": "responder",
                "reply": "Quer fechar com esse plano ou prefere cotar outro?",
            }

        # ---- confirmando
        if stage == "confirmando" and not novos:
            if "aceite" in ex.intents:
                return pedir_nova_data() if data_vencida() else {**base, "acao": "cotar"}
            if "negacao" in ex.intents:
                return {
                    **base,
                    "acao": "responder",
                    "stage": "coletando",
                    "awaiting": None,
                    "reply": T.CORRIGIR,
                }
            return {**base, "acao": "responder", "reply": T.confirmar(slots, cep_prefixo)}

        # ---- coletando: pergunta o que falta, na ordem
        faltando = [c for c in CAMPOS if not slots.get(c)]
        prefix = T.saudacao() if stage == "novo" else ""
        mostrados = bool(state.get("planos_mostrados"))
        if (
            "pergunta_planos" in ex.intents
            and "plano_id" in faltando
            and faltando[0] != "plano_id"
            and not mostrados
        ):
            prefix += (
                T.perguntar("plano_id", await planos()).replace("\nQual deles você quer cotar?", "") + "\n"
            )
            mostrados = True
        if faltando:
            campo = faltando[0]
            # a lista de planos aparece uma vez só; depois, pergunta curta
            pergunta = T.perguntar(campo, [] if (campo == "plano_id" and mostrados) else await planos())
            return {
                **base,
                "acao": "responder",
                "stage": "coletando",
                "awaiting": campo,
                "planos_mostrados": mostrados or campo == "plano_id",
                "reply": prefix + pergunta,
            }
        return {
            **base,
            "acao": "responder",
            "stage": "confirmando",
            "awaiting": "confirmacao",
            "reply": prefix + T.confirmar(slots, cep_prefixo),
        }

    # ------------------------------------------------------------------ cotar
    async def cotar(state: AgentState) -> dict[str, Any]:
        slots = state["slots"]
        vault = PiiVault.from_dict(state.get("vault"))
        cep = vault.reveal(slots["cep"]) if str(slots.get("cep", "")).startswith("[") else slots.get("cep")
        try:
            out = await gateway.cotar(
                plano_id=slots["plano_id"],
                idade=int(slots["idade"]),
                veiculo_ano=int(slots["veiculo_ano"]),
                cep=cep,
                data_inicio=slots.get("data_inicio"),
            )
        except Exception as e:  # noqa: BLE001 - ferramenta fora: sem preço, segue para humano
            out = {
                "status": "indisponivel",
                "quote_request_id": None,
                "motivo": f"ferramenta: {type(e).__name__}",
            }
        ev = _event(
            state,
            "cotacao",
            quote_request_id=out["quote_request_id"],
            status=out["status"],
            quote_id=out.get("quote_id"),
            from_cache=out.get("from_cache"),
            latency_ms=out.get("latency_ms"),
            attempts=[
                {k: a[k] for k in ("n", "http_status", "outcome", "latency_ms", "hedge")}
                for a in out.get("attempts", [])
            ],
            premio_mensal=(out.get("quote") or {}).get("premio_mensal"),
        )
        match out["status"]:
            case "ok":
                q = {**out["quote"], "_quote_id": out["quote_id"]}
                de_fundo = state.get("stage") == "aguardando_cotacao"
                prefixo = T.CONSEGUI if de_fundo else state.get("reply_prefix", "")
                return {
                    "stage": "cotado",
                    "awaiting": None,
                    "quote_atual": q,
                    "quotes": [*state.get("quotes", []), q],
                    "tentativas_fundo": 0,
                    "acao": "responder",
                    "reply": prefixo + T.apresentar(q),
                    "events": [ev],
                }
            case "recusada":
                return {
                    "acao": "handoff",
                    "handoff_pendente": {"motivo": "recusa_regra", "detalhe": out["motivo"]},
                    "events": [ev],
                }
            case "invalida":
                return {"acao": "responder", "stage": "coletando", "reply": T.CORRIGIR, "events": [ev]}
            case _:  # indisponivel | circuito_aberto
                feitas = state.get("tentativas_fundo", 0)
                if feitas < len(retry_delays):
                    # não trava e não inventa: avisa uma vez e tenta de novo em segundo plano
                    primeira = state.get("stage") != "aguardando_cotacao"
                    return {
                        "stage": "aguardando_cotacao",
                        "awaiting": None,
                        "acao": "responder",
                        "agendar_retry": retry_delays[feitas],
                        "reply": T.AGUARDANDO_COTACAO if primeira else "",
                        "events": [
                            ev,
                            _event(
                                state, "retry_agendado", em_s=retry_delays[feitas], tentativa_fundo=feitas + 1
                            ),
                        ],
                    }
                return {
                    "acao": "handoff",
                    "tentativas_fundo": 0,
                    "handoff_pendente": {"motivo": "cotacao_indisponivel", "detalhe": out.get("motivo")},
                    "events": [ev],
                }

    # ------------------------------------------------------------------ handoff
    async def handoff(state: AgentState) -> dict[str, Any]:
        hp = state["handoff_pendente"]
        slots = {**(state.get("slots") or {})}
        if slots.get("cep"):
            slots["cep"] = f"{state.get('cep_prefixo') or '??'}xxx-xxx"
        q = state.get("quote_atual")
        resumo_linhas = [f"{m['role']}: {m['text']}" for m in (state.get("transcript") or [])[-8:]]
        dados = {
            "slots": slots,
            "detalhe": hp.get("detalhe"),
            "cotacao": {k: q.get(k) for k in ("plano_id", "premio_mensal", "franquia", "_quote_id")}
            if q
            else None,
        }
        try:
            item = await gateway.registrar_handoff(
                conversation_id=state["conversation_id"],
                motivo=hp["motivo"],
                resumo="\n".join(resumo_linhas),
                dados=dados,
            )
        except Exception as e:  # noqa: BLE001 - lead não fica sem resposta; evento alerta a operação
            item = {
                "handoff_id": None,
                "motivo": hp["motivo"],
                "status": f"falha_registro:{type(e).__name__}",
            }
        reply = T.recusa(hp.get("detalhe")) if hp["motivo"] == "recusa_regra" else T.HANDOFF[hp["motivo"]]
        return {
            "stage": "handoff",
            "stage_antes_handoff": state.get("stage"),
            "awaiting": None,
            "handoff": item,
            "acao": "responder",
            "reply": reply,
            "events": [
                _event(
                    state,
                    "handoff",
                    motivo=hp["motivo"],
                    handoff_id=item["handoff_id"],
                    detalhe=hp.get("detalhe"),
                )
            ],
        }

    # ------------------------------------------------------------------ saida
    async def saida(state: AgentState) -> dict[str, Any]:
        if not state.get("reply") and (state.get("incoming") or {}).get("message_type") == "system":
            return {"reply": ""}  # tentativa em segundo plano sem novidade: silêncio
        reply = state.get("reply") or T.FALLBACK_SEGURO
        permitidos = T.valores_permitidos(state.get("quotes") or [])
        events = []
        if redator is not None and state.get("ponte") and state.get("stage") != "handoff":
            frase = await redator.ponte(state.get("turn_text", ""), reply)
            if frase and check_output(f"{frase} {reply}", permitidos).ok:
                reply = f"{frase}\n{reply}"
            events.append(_event(state, "redator", usada=bool(frase)))
        chk = check_output(reply, permitidos)
        if not chk.ok:
            events.append(_event(state, "guardrail_saida_bloqueou", violacoes=chk.violacoes))
            reply = T.FALLBACK_SEGURO
        out_id = f"msg_{uuid.uuid4().hex[:12]}"
        events.append(
            _event(state, "message_out", out_message_id=out_id, text=reply, stage=state.get("stage"))
        )
        return {
            "reply": reply,
            "transcript": [{"role": "agente", "text": reply, "message_id": out_id}],
            "events": events,
        }

    # ------------------------------------------------------------------ aguardar_humano
    async def aguardar_humano(state: AgentState) -> dict[str, Any]:
        """Pausa a conversa (interrupt) até o operador decidir. Retomada por Command(resume=...)."""
        decisao = interrupt({"tipo": "handoff", "handoff": state.get("handoff")})
        acao = (decisao or {}).get("acao")
        ev = _event(state, "operador", acao=acao)
        if acao == "devolver":
            slots = state.get("slots") or {}
            faltando = [c for c in CAMPOS if not slots.get(c)]
            base = {
                "handoff": None,
                "handoff_pendente": None,
                "midia_count": 0,
                "objecoes": 0,
                "turnos_sem_progresso": 0,
                "tentativas_fundo": 0,
                "events": [ev],
            }
            if faltando:
                return {
                    **base,
                    "stage": "coletando",
                    "awaiting": faltando[0],
                    "reply": T.VOLTEI + T.perguntar(faltando[0], await planos()),
                }
            return {
                **base,
                "stage": "confirmando",
                "awaiting": "confirmacao",
                "reply": T.VOLTEI + T.confirmar(slots, state.get("cep_prefixo")),
            }
        return {"stage": "encerrado", "handoff_pendente": None, "reply": T.ENCERRADO, "events": [ev]}

    def rota_saida(state: AgentState) -> str:
        acabou_de_ir = state.get("stage") == "handoff" and state.get("handoff_pendente")
        return "aguardar_humano" if acabou_de_ir else END

    def rota_decidir(state: AgentState) -> str:
        return {"cotar": "cotar", "handoff": "handoff"}.get(state.get("acao", ""), "saida")

    def rota_cotar(state: AgentState) -> str:
        return "handoff" if state.get("acao") == "handoff" else "saida"

    g = StateGraph(AgentState)
    g.add_node("entrada", entrada)
    g.add_node("decidir", decidir)
    g.add_node("cotar", cotar)
    g.add_node("handoff", handoff)
    g.add_node("saida", saida)
    g.add_node("aguardar_humano", aguardar_humano)
    g.add_edge(START, "entrada")
    g.add_edge("entrada", "decidir")
    g.add_conditional_edges(
        "decidir", rota_decidir, {"cotar": "cotar", "handoff": "handoff", "saida": "saida"}
    )
    g.add_conditional_edges("cotar", rota_cotar, {"handoff": "handoff", "saida": "saida"})
    g.add_edge("handoff", "saida")
    g.add_conditional_edges("saida", rota_saida, {"aguardar_humano": "aguardar_humano", END: END})
    g.add_edge("aguardar_humano", "saida")
    return g.compile(checkpointer=checkpointer)
