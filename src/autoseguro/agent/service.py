"""Fachada do agente: monta ferramentas, checkpointer e grafo; expõe `handle` por mensagem."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from autoseguro.agent.extract import Extractor
from autoseguro.agent.gateway import ToolGateway
from autoseguro.agent.graph import build_graph
from autoseguro.config import Settings
from autoseguro.tools.mcp_server import Services, build_server


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

    async def handle(
        self, conversation_id: str, text: str, message_type: str = "text", message_id: str | None = None
    ) -> dict[str, Any]:
        message_id = message_id or f"msg_{uuid.uuid4().hex[:12]}"
        cfg = {"configurable": {"thread_id": conversation_id}}
        st = await self.graph.ainvoke(
            {
                "conversation_id": conversation_id,
                "incoming": {"message_id": message_id, "text": text, "message_type": message_type},
            },
            cfg,
        )
        return {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "reply": st["reply"],
            "stage": st.get("stage"),
            "handoff": st.get("handoff"),
            "quote_id": (st.get("quote_atual") or {}).get("_quote_id"),
        }

    async def trace(self, conversation_id: str) -> dict[str, Any] | None:
        snap = await self.graph.aget_state({"configurable": {"thread_id": conversation_id}})
        if not snap or not snap.values:
            return None
        v = snap.values
        return {  # sem vault: só dados mascarados saem daqui
            "conversation_id": conversation_id,
            "stage": v.get("stage"),
            "slots": {
                **(v.get("slots") or {}),
                **({"cep": f"{v.get('cep_prefixo')}xxx-xxx"} if v.get("slots", {}).get("cep") else {}),
            },
            "handoff": v.get("handoff"),
            "transcript": v.get("transcript", []),
            "events": v.get("events", []),
        }
