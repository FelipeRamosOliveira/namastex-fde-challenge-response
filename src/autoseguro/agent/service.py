"""Fachada do agente: monta ferramentas, checkpointer e grafo; expõe `handle` por mensagem.

Garantias desta camada:
- Serialização por conversa: lock por conversa (asyncio num processo, Redis entre réplicas).
- O texto bruto nunca entra no grafo nem no checkpoint: é mascarado aqui, antes do `ainvoke`.
- Id opaco: o id do canal (no Omni costuma ser o telefone) vira `conversation_ref` (hash).
- Idempotência: reenvio do mesmo `message_id` devolve a mesma resposta sem reprocessar.
- Cotação em segundo plano: se a /quote falhar, o grafo pede nova tentativa; esta camada agenda,
  reexecuta o grafo com um evento de sistema e entrega o resultado pelo `Outbox`. As tentativas
  pendentes ficam no KVStore e são reagendadas se o processo reiniciar.
- Humano no circuito: no handoff o grafo pausa (`interrupt`). Mensagens do lead durante a pausa
  entram no histórico via `aupdate_state` sem acordar o grafo; o operador responde, devolve a
  conversa ao bot ou encerra (`Command(resume=...)`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from autoseguro.agent import templates as T
from autoseguro.agent.extract import Extractor
from autoseguro.agent.gateway import ToolGateway
from autoseguro.agent.graph import EVENTO_RETENTAR, build_graph
from autoseguro.agent.llm_extract import LLMExtractor
from autoseguro.agent.outbox import Outbox
from autoseguro.agent.redator import Redator
from autoseguro.channels.omni import OmniDelivery
from autoseguro.config import Settings
from autoseguro.guardrails.pii import PiiVault, configurar_chave_vault, mask
from autoseguro.llm.client import LLMClient, providers_from_settings
from autoseguro.tools.handoff import HandoffQueue
from autoseguro.tools.mcp_server import Services, build_server
from autoseguro.tools.store import KVStore, make_store

MAX_DEDUP = 5000
log = logging.getLogger("autoseguro")
trace_log = logging.getLogger("autoseguro.trace")
PENDENTES_KEY = "retry:pendentes"
NO_PAUSADO = ("aguardar_humano",)


def conversation_ref(conversation_id: str) -> str:
    return "conv_" + hashlib.sha256(conversation_id.encode()).hexdigest()[:16]


def _agora() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class AutoSeguroAgent:
    def __init__(
        self,
        settings: Settings,
        extractor: Extractor | None = None,
        services: Services | None = None,
        hoje=None,
        llm: LLMClient | None = None,
        outbox: Outbox | None = None,
    ) -> None:
        self.s, self.extractor, self._services, self._hoje = settings, extractor, services, hoje
        self._llm = llm
        self._outbox = outbox
        self.llm: LLMClient | None = None
        self._stack = AsyncExitStack()
        self.graph = None
        self.services: Services | None = None
        self.store: KVStore | None = None
        self.outbox: Outbox | None = None
        self.handoffs: HandoffQueue | None = None
        self._dedup: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ ciclo de vida
    async def __aenter__(self) -> AutoSeguroAgent:
        configurar_chave_vault(self.s.vault_key.get_secret_value() if self.s.vault_key else None)
        if not self.s.vault_key:
            log.warning("VAULT_KEY não definida: CEP fica sem cifra no checkpoint (só desenvolvimento)")
        if self.s.mcp_url:
            target = self.s.mcp_url
            self.store = make_store(self.s.redis_url)
        else:
            self.services = self._services or Services.from_settings(self.s)
            target = build_server(self.services)
            self.store = self.services.store
        self.omni = None
        if self.s.omni_url and self.s.omni_api_key:
            self.omni = OmniDelivery(self.s.omni_url, self.s.omni_api_key.get_secret_value(), self.store)
        self.outbox = self._outbox or Outbox(self.store, self.s.outbound_webhook_url, omni=self.omni)
        self.handoffs = HandoffQueue(self.store)
        gateway = await self._stack.enter_async_context(ToolGateway(target))
        Path(self.s.checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        saver = await self._stack.enter_async_context(AsyncSqliteSaver.from_conn_string(self.s.checkpoint_db))
        kw: dict[str, Any] = {
            "max_turnos_sem_progresso": self.s.max_turnos_sem_progresso,
            "retry_delays": tuple(self.s.retry_fundo_delays_s),
        }
        if self._hoje:
            kw["hoje"] = self._hoje
        extractor, redator = self.extractor, None
        llm = self._llm or self._build_llm()
        if llm is not None and llm.available:
            extractor = extractor or LLMExtractor(llm)
            redator = Redator(llm) if self.s.usar_redator else None
        self.llm = llm
        self.graph = build_graph(gateway, extractor, saver, redator=redator, **kw)
        try:  # aquece: conexão MCP e cache do /planos antes do primeiro lead
            await gateway.consultar_planos()
        except Exception:  # noqa: BLE001, S110 - sem aquecimento, o primeiro turno só fica mais lento
            pass
        await self._reagendar_pendentes()
        return self

    async def __aexit__(self, *exc) -> None:
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await self._stack.aclose()

    def _build_llm(self) -> LLMClient | None:
        providers = providers_from_settings(self.s)
        if not providers:
            return None
        return LLMClient(providers, self.store, timeout_s=self.s.llm_timeout_s)

    @staticmethod
    def _cfg(ref: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": ref}}

    # ------------------------------------------------------------------ mensagem do lead
    async def handle(
        self, conversation_id: str, text: str, message_type: str = "text", message_id: str | None = None
    ) -> dict[str, Any]:
        ref = conversation_ref(conversation_id)
        message_id = message_id or f"msg_{uuid.uuid4().hex[:12]}"
        cfg = self._cfg(ref)
        async with self.store.lock(f"conv:{ref}"):
            if (ref, message_id) in self._dedup:
                return {**self._dedup[(ref, message_id)], "duplicada": True}
            snap = await self.graph.aget_state(cfg)
            vault = PiiVault.from_dict((snap.values or {}).get("vault") if snap else None)
            masked = mask(text, vault)

            antes = len((snap.values or {}).get("events", [])) if snap else 0
            if snap and snap.next == NO_PAUSADO:
                st = await self._mensagem_durante_handoff(ref, cfg, message_id, masked, vault, message_type)
            else:
                st = await self.graph.ainvoke(
                    {
                        "conversation_id": ref,
                        "vault": vault.to_dict(),
                        "incoming": {
                            "message_id": message_id,
                            "text": masked.text,
                            "message_type": message_type,
                        },
                    },
                    cfg,
                )
                await self._talvez_agendar(ref, conversation_id, st)
            self._log_eventos(st, antes)
            out = self._resposta(conversation_id, ref, message_id, st)
            self._dedup[(ref, message_id)] = out
            while len(self._dedup) > MAX_DEDUP:
                self._dedup.popitem(last=False)
            return out

    @staticmethod
    def _log_eventos(st: dict[str, Any], antes: int) -> None:
        """Log estruturado (JSON por linha) dos eventos novos do turno: já mascarados."""
        for e in (st.get("events") or [])[antes:]:
            trace_log.info(json.dumps(e, ensure_ascii=False, default=str))

    @staticmethod
    def _resposta(conversation_id: str, ref: str, message_id: str, st: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "conversation_ref": ref,
            "message_id": message_id,
            "reply": st.get("reply", ""),
            "stage": st.get("stage"),
            "handoff": st.get("handoff"),
            "quote_id": (st.get("quote_atual") or {}).get("_quote_id"),
        }

    async def _mensagem_durante_handoff(self, ref, cfg, message_id, masked, vault, message_type):
        """Conversa pausada com o humano: registra a mensagem sem acordar o grafo."""
        out_id = f"msg_{uuid.uuid4().hex[:12]}"
        base = {"conversation_id": ref, "message_id": message_id, "ts": _agora()}
        await self.graph.aupdate_state(
            cfg,
            {
                "vault": vault.to_dict(),
                "transcript": [
                    {
                        "role": "lead",
                        "text": masked.text,
                        "message_id": message_id,
                        "message_type": message_type,
                    },
                    {"role": "agente", "text": T.POS_HANDOFF, "message_id": out_id},
                ],
                "events": [
                    {
                        **base,
                        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                        "type": "message_in",
                        "text": masked.text,
                        "durante_handoff": True,
                    },
                    {
                        **base,
                        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                        "type": "message_out",
                        "out_message_id": out_id,
                        "text": T.POS_HANDOFF,
                        "stage": "handoff",
                    },
                ],
            },
            as_node="saida",  # mantém o próximo passo em aguardar_humano
        )
        st = (await self.graph.aget_state(cfg)).values
        return {**st, "reply": T.POS_HANDOFF}

    # ------------------------------------------------------------------ cotação em segundo plano
    async def _talvez_agendar(self, ref: str, conversation_id: str, st: dict[str, Any]) -> None:
        delay = st.get("agendar_retry")
        if delay is None:
            return
        pend = (await self.store.get_json(PENDENTES_KEY)) or {}
        pend[ref] = {"conversation_id": conversation_id, "due": time.time() + delay}
        await self.store.set_json(PENDENTES_KEY, pend)
        self._spawn(self._retentar(ref, conversation_id, delay))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _reagendar_pendentes(self) -> None:
        pend = (await self.store.get_json(PENDENTES_KEY)) or {}
        for ref, item in pend.items():
            self._spawn(self._retentar(ref, item["conversation_id"], max(0.0, item["due"] - time.time())))

    async def _retentar(self, ref: str, conversation_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        cfg = self._cfg(ref)
        async with self.store.lock(f"conv:{ref}"):
            pend = (await self.store.get_json(PENDENTES_KEY)) or {}
            pend.pop(ref, None)
            await self.store.set_json(PENDENTES_KEY, pend)
            snap = await self.graph.aget_state(cfg)
            if not snap or (snap.values or {}).get("stage") != "aguardando_cotacao":
                return  # a conversa seguiu (ex.: lead pediu humano)
            antes = len((snap.values or {}).get("events", []))
            st = await self.graph.ainvoke(
                {
                    "conversation_id": ref,
                    "incoming": {
                        "message_id": f"sys_{uuid.uuid4().hex[:12]}",
                        "text": EVENTO_RETENTAR,
                        "message_type": "system",
                    },
                },
                cfg,
            )
            self._log_eventos(st, antes)
            if st.get("reply"):
                await self.outbox.push(ref, conversation_id, st["reply"], "agente")
            await self._talvez_agendar(ref, conversation_id, st)

    # ------------------------------------------------------------------ operador humano
    async def operador(self, conversation_id: str, acao: str, texto: str | None = None) -> dict[str, Any]:
        """acao: responder (texto ao lead), devolver (conversa volta ao bot) ou encerrar."""
        ref = conversation_ref(conversation_id)
        cfg = self._cfg(ref)
        async with self.store.lock(f"conv:{ref}"):
            snap = await self.graph.aget_state(cfg)
            if not snap or snap.next != NO_PAUSADO:
                raise ValueError("conversa não está com um humano")
            if acao == "responder":
                if not texto:
                    raise ValueError("texto obrigatório")
                vault = PiiVault.from_dict(snap.values.get("vault"))
                item = await self.outbox.push(ref, conversation_id, texto, "humano")
                await self.graph.aupdate_state(
                    cfg,
                    {
                        "vault": vault.to_dict(),
                        "transcript": [
                            {
                                "role": "humano",
                                "text": mask(texto, vault).text,
                                "message_id": item["message_id"],
                            }
                        ],
                        "events": [
                            {
                                "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                                "ts": _agora(),
                                "conversation_id": ref,
                                "type": "operador",
                                "acao": "responder",
                                "out_message_id": item["message_id"],
                            }
                        ],
                    },
                    as_node="saida",
                )
                return {"ok": True, "entregue": item}
            if acao not in ("devolver", "encerrar"):
                raise ValueError("acao inválida")
            st = await self.graph.ainvoke(Command(resume={"acao": acao}), cfg)
            item = (
                await self.outbox.push(ref, conversation_id, st["reply"], "agente")
                if st.get("reply")
                else None
            )
            return {"ok": True, "stage": st.get("stage"), "entregue": item}

    # ------------------------------------------------------------------ leitura
    async def mensagens_ativas(self, conversation_id: str, depois_de: int = 0) -> list[dict[str, Any]]:
        return await self.outbox.listar(conversation_ref(conversation_id), depois_de)

    async def trace(self, conversation_id: str) -> dict[str, Any] | None:
        ref = conversation_ref(conversation_id)
        snap = await self.graph.aget_state(self._cfg(ref))
        if not snap or not snap.values:
            return None
        v = snap.values
        slots = dict(v.get("slots") or {})
        if slots.get("cep"):
            slots["cep"] = f"{v.get('cep_prefixo') or '??'}xxx-xxx"
        return {  # sem vault: só dados mascarados saem daqui
            "conversation_ref": ref,
            "stage": v.get("stage"),
            "pausado_com_humano": snap.next == NO_PAUSADO,
            "slots": slots,
            "handoff": v.get("handoff"),
            "transcript": v.get("transcript", []),
            "events": v.get("events", []),
        }

    async def historico(self, conversation_id: str) -> list[dict[str, Any]]:
        """Viagem no tempo: cada checkpoint da conversa (passo do grafo), do mais antigo ao mais novo.
        `executou` é o nó que rodou para chegar a este checkpoint (o `next` do checkpoint anterior)."""
        ref = conversation_ref(conversation_id)
        snaps = [h async for h in self.graph.aget_state_history(self._cfg(ref))]
        passos, anterior = [], ()
        for h in reversed(snaps):
            v = h.values or {}
            passos.append(
                {
                    "checkpoint_id": h.config["configurable"].get("checkpoint_id"),
                    "criado_em": h.created_at,
                    "passo": (h.metadata or {}).get("step"),
                    "executou": list(anterior),
                    "proximo": list(h.next),
                    "stage": v.get("stage"),
                    "awaiting": v.get("awaiting"),
                }
            )
            anterior = h.next
        return passos
