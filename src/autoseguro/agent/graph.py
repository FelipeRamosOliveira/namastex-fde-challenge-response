"""Grafo LangGraph do atendimento.

    entrada ─▶ decidir ─┬─▶ cotar ───┬─▶ saida ─▶ END
       (PII)            │            └─▶ handoff ─▶ saida
                        ├─▶ handoff ─▶ saida
                        └─▶ saida

- entrada: guardrail de PII (mascara e guarda originais no vault da conversa)
- decidir: extrai dados/intenções, pré-valida regras, escolhe o próximo passo
- cotar:   chama a ferramenta MCP `cotar`; resposta montada por template com valores da API
- handoff: registra na fila do vendedor com resumo mascarado
- saida:   guardrail de saída (PII + valores em R$ só da API) e evento de rastreio

Estado persistido por conversa (thread_id = conversation_id) no checkpointer.
"""

from __future__ import annotations

import operator
import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from autoseguro.agent import templates as T
from autoseguro.agent.extract import CAMPOS, Extractor, RuleExtractor
from autoseguro.agent.gateway import ToolGateway
from autoseguro.guardrails.output import check_output
from autoseguro.guardrails.pii import PiiKind, PiiVault, mask

Stage = Literal["novo", "coletando", "confirmando", "cotado", "handoff"]


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
    quotes: list[dict[str, Any]]  # respostas OK da API (fonte dos valores permitidos)
    quote_atual: dict[str, Any] | None
    handoff: dict[str, Any] | None
    handoff_pendente: dict[str, Any] | None
    turnos_sem_progresso: int
    midia_count: int
    objecoes: int
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
):
    extractor = extractor or RuleExtractor()
    planos_cache: dict[str, Any] = {}

    async def planos() -> list[dict[str, Any]]:
        if not planos_cache:
            planos_cache.update(await gateway.consultar_planos())
        return planos_cache["planos"]

    # ------------------------------------------------------------------ entrada
    async def entrada(state: AgentState) -> dict[str, Any]:
        vault = PiiVault.from_dict(state.get("vault"))
        inc = state["incoming"]
        masked = mask(inc["text"], vault)
        cep_orig = vault.latest(PiiKind.CEP)
        upd: dict[str, Any] = {
            "turn_text": masked.text,
            "vault": vault.to_dict(),
            "reply": "",
            "reply_prefix": "",
            "handoff_pendente": None,
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
        if cep_orig:
            upd["cep_prefixo"] = re.sub(r"\D", "", cep_orig)[:2]
        if not state.get("stage"):
            upd.update(stage="novo", slots={}, quotes=[], turnos_sem_progresso=0, midia_count=0, objecoes=0)
        return upd

    # ------------------------------------------------------------------ decidir
    async def decidir(state: AgentState) -> dict[str, Any]:
        stage = state.get("stage", "novo")
        if stage == "handoff":
            return {"acao": "responder", "reply": T.POS_HANDOFF}

        hj = hoje()
        text = state["turn_text"]
        if state.get("incoming", {}).get("message_type", "text") != "text" and not text.startswith("["):
            text = f"[{state['incoming']['message_type']}] {text}"
        ex = await extractor.extract(text, state.get("awaiting"), hj)
        events = [
            _event(
                state, "extracao", slots={k: str(v) for k, v in ex.slots.items()}, intents=sorted(ex.intents)
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
            ask = T.perguntar(state["awaiting"], await planos()) if state.get("awaiting") else ""
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

        # ---- pré-validação das regras (sem gastar chamada na /quote)
        if {"idade", "veiculo_ano"} & novos.keys():
            pv = await gateway.pre_validar(idade=slots.get("idade"), veiculo_ano=slots.get("veiculo_ano"))
            events.append(_event(state, "pre_validacao", **pv))
            if not pv["ok"]:
                return {**handoff("recusa_regra", pv["motivo"]), "slots": slots}

        progresso = bool(novos) or bool(ex.intents & {"aceite", "negacao", "pergunta_planos"})
        sem_prog = 0 if progresso else state.get("turnos_sem_progresso", 0) + 1
        base = {"slots": slots, "turnos_sem_progresso": sem_prog, "events": events}
        if sem_prog >= max_turnos_sem_progresso:
            return {**handoff("sem_progresso"), "slots": slots}

        # ---- já cotado: fechar, trocar plano ou objeção
        if stage == "cotado":
            atual = (state.get("quote_atual") or {}).get("plano_id")
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
                return {**base, "acao": "cotar"}
            if "negacao" in ex.intents:
                return {
                    **base,
                    "acao": "responder",
                    "stage": "coletando",
                    "awaiting": None,
                    "reply": T.CORRIGIR,
                }
            return {**base, "acao": "responder", "reply": T.confirmar(slots, state.get("cep_prefixo"))}

        # ---- coletando: pergunta o que falta, na ordem
        faltando = [c for c in CAMPOS if not slots.get(c)]
        prefix = T.saudacao() if stage == "novo" else ""
        if "pergunta_planos" in ex.intents and "plano_id" in faltando and faltando[0] != "plano_id":
            prefix += (
                T.perguntar("plano_id", await planos()).replace("\nQual deles você quer cotar?", "") + "\n"
            )
        if faltando:
            campo = faltando[0]
            return {
                **base,
                "acao": "responder",
                "stage": "coletando",
                "awaiting": campo,
                "reply": prefix + T.perguntar(campo, await planos()),
            }
        return {
            **base,
            "acao": "responder",
            "stage": "confirmando",
            "awaiting": "confirmacao",
            "reply": prefix + T.confirmar(slots, state.get("cep_prefixo")),
        }

    # ------------------------------------------------------------------ cotar
    async def cotar(state: AgentState) -> dict[str, Any]:
        slots = state["slots"]
        vault = PiiVault.from_dict(state.get("vault"))
        cep = vault.reveal(slots["cep"]) if str(slots.get("cep", "")).startswith("[") else slots.get("cep")
        out = await gateway.cotar(
            plano_id=slots["plano_id"],
            idade=int(slots["idade"]),
            veiculo_ano=int(slots["veiculo_ano"]),
            cep=cep,
            data_inicio=slots.get("data_inicio"),
        )
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
                return {
                    "stage": "cotado",
                    "awaiting": None,
                    "quote_atual": q,
                    "quotes": [*state.get("quotes", []), q],
                    "acao": "responder",
                    "reply": state.get("reply_prefix", "") + T.apresentar(q),
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
            case _:  # indisponivel | circuito_aberto (etapa 5: nova tentativa em segundo plano)
                return {
                    "acao": "handoff",
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
        item = await gateway.registrar_handoff(
            conversation_id=state["conversation_id"],
            motivo=hp["motivo"],
            resumo="\n".join(resumo_linhas),
            dados=dados,
        )
        reply = T.recusa(hp.get("detalhe")) if hp["motivo"] == "recusa_regra" else T.HANDOFF[hp["motivo"]]
        return {
            "stage": "handoff",
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
        reply = state.get("reply") or T.FALLBACK_SEGURO
        chk = check_output(reply, T.valores_permitidos(state.get("quotes") or []))
        events = []
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
    g.add_edge(START, "entrada")
    g.add_edge("entrada", "decidir")
    g.add_conditional_edges(
        "decidir", rota_decidir, {"cotar": "cotar", "handoff": "handoff", "saida": "saida"}
    )
    g.add_conditional_edges("cotar", rota_cotar, {"handoff": "handoff", "saida": "saida"})
    g.add_edge("handoff", "saida")
    g.add_edge("saida", END)
    return g.compile(checkpointer=checkpointer)
