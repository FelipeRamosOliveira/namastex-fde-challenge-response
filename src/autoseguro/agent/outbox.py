"""Mensagens ativas para o lead (fora da resposta síncrona): cotação que saiu em segundo
plano, resposta do atendente, devolução da conversa ao bot.

Guarda em uma lista por conversa (KVStore/Redis) e, se OUTBOUND_WEBHOOK_URL estiver
configurada, entrega no canal (ex.: Omni). O canal consulta `GET /v1/conversations/{id}/outbox`
quando não há webhook.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import httpx

from autoseguro.tools.store import KVStore


class Outbox:
    def __init__(
        self,
        store: KVStore,
        webhook_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        omni: Any = None,
    ) -> None:
        self.store, self.webhook_url, self.omni = store, webhook_url, omni
        self.http = http or httpx.AsyncClient(timeout=5)

    async def push(
        self, conversation_ref: str, conversation_id: str, texto: str, origem: str
    ) -> dict[str, Any]:
        item = {
            "message_id": f"out_{uuid.uuid4().hex[:12]}",
            "conversation_id": conversation_id,
            "texto": texto,
            "origem": origem,  # agente | humano
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "entregue_webhook": False,
            "entregue_omni": False,
        }
        if self.omni is not None:  # conversa que veio do Omni volta pelo Omni
            try:
                res = await self.omni.enviar(conversation_ref, texto)
                item["entregue_omni"] = bool(res) and res["status"] < 300
            except httpx.HTTPError:
                pass
        if self.webhook_url:
            try:
                r = await self.http.post(self.webhook_url, json=item)
                item["entregue_webhook"] = r.status_code < 300
            except httpx.HTTPError:
                pass  # fica no outbox para o canal buscar
        await self.store.push(f"outbox:{conversation_ref}", item)
        return item

    async def listar(self, conversation_ref: str, depois_de: int = 0) -> list[dict[str, Any]]:
        return (await self.store.list_all(f"outbox:{conversation_ref}"))[depois_de:]
