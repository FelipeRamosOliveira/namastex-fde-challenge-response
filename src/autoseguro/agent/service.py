"""Fachada do agente: monta ferramentas, checkpointer e grafo; expõe `handle` por mensagem.

Garantias desta camada:
- Serialização por conversa: mensagens em rajada da mesma conversa são processadas
  uma de cada vez (lock por conversa), sem perder turnos nem dados.
- O texto bruto nunca entra no grafo nem no checkpoint: é mascarado aqui, com o vault
  da conversa, antes do `ainvoke`.
- Id opaco: o id do canal (no Omni costuma ser o telefone) vira `conversation_ref`
  (hash) em estado, eventos e fila de handoff.
- Idempotência: reenvio do mesmo `message_id` devolve a mesma resposta sem reprocessar.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import OrderedDict
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from autoseguro.agent.extract import Extractor
from autoseguro.agent.gateway import ToolGateway
from autoseguro.agent.graph import build_graph
from autoseguro.config import Settings
from autoseguro.guardrails.pii import PiiVault, mask
from autoseguro.tools.mcp_server import Services, build_server

MAX_DEDUP = 5000


def conversation_ref(conversation_id: str) -> str:
    return "conv_" + hashlib.sha256(conversation_id.encode()).hexdigest()[:16]


class AutoSeguroAgent:
    def __init__(
        self,
        settings: Settings,
        extractor: Extractor | None = None,
        services: Services | None = None,
        hoje=None,
    ) -> None:
        self.s, self.extractor, self._services, self._hoje = settings, extractor, services, hoje
        self._stack = AsyncExitStack()
        self.graph = None
        self.services: Services | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._dedup: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    async def __aenter__(self) -> AutoSeguroAgent:
        if self.s.mcp_url:
            target = self.s.mcp_url
        else:
            self.services = self._services or Services.from_settings(self.s)
            target = build_server(self.services)
        gateway = await self._stack.enter_async_context(ToolGateway(target))
        Path(self.s.checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        saver = await self._stack.enter_async_context(AsyncSqliteSaver.from_conn_string(self.s.checkpoint_db))
        kw: dict[str, Any] = {"max_turnos_sem_progresso": self.s.max_turnos_sem_progresso}
        if self._hoje:
            kw["hoje"] = self._hoje
        self.graph = build_graph(gateway, self.extractor, saver, **kw)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    def _lock(self, ref: str) -> asyncio.Lock:
        # Um processo: asyncio.Lock. Com várias réplicas, trocar por lock no Redis (etapa 5).
        return self._locks.setdefault(ref, asyncio.Lock())

    async def handle(
        self, conversation_id: str, text: str, message_type: str = "text", message_id: str | None = None
    ) -> dict[str, Any]:
        ref = conversation_ref(conversation_id)
        message_id = message_id or f"msg_{uuid.uuid4().hex[:12]}"
        cfg = {"configurable": {"thread_id": ref}}
        async with self._lock(ref):
            if (ref, message_id) in self._dedup:
                return {**self._dedup[(ref, message_id)], "duplicada": True}
            snap = await self.graph.aget_state(cfg)
            vault = PiiVault.from_dict((snap.values or {}).get("vault") if snap else None)
            masked = mask(text, vault)
            st = await self.graph.ainvoke(
                {
                    "conversation_id": ref,
                    "vault": vault.to_dict(),
                    "incoming": {"message_id": message_id, "text": masked.text, "message_type": message_type},
                },
                cfg,
            )
            out = {
                "conversation_id": conversation_id,
                "conversation_ref": ref,
                "message_id": message_id,
                "reply": st["reply"],
                "stage": st.get("stage"),
                "handoff": st.get("handoff"),
                "quote_id": (st.get("quote_atual") or {}).get("_quote_id"),
            }
            self._dedup[(ref, message_id)] = out
            while len(self._dedup) > MAX_DEDUP:
                self._dedup.popitem(last=False)
            return out

    async def trace(self, conversation_id: str) -> dict[str, Any] | None:
        ref = conversation_ref(conversation_id)
        snap = await self.graph.aget_state({"configurable": {"thread_id": ref}})
        if not snap or not snap.values:
            return None
        v = snap.values
        slots = dict(v.get("slots") or {})
        if slots.get("cep"):
            slots["cep"] = f"{v.get('cep_prefixo') or '??'}xxx-xxx"
        return {  # sem vault: só dados mascarados saem daqui
            "conversation_ref": ref,
            "stage": v.get("stage"),
            "slots": slots,
            "handoff": v.get("handoff"),
            "transcript": v.get("transcript", []),
            "events": v.get("events", []),
        }
