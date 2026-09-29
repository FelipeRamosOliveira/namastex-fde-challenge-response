"""Canal Omni (automagik-dev/omni): o agente é um *provider* `webhook` do Omni.

Contrato lido do código do Omni (packages/core/src/providers/webhook-provider.ts e types.ts,
commit 906a420, 24/09/2026):

Entrada (Omni -> agente), modo round-trip:
    POST <webhookUrl>
    Authorization: Bearer <apiKey do provider>     X-Omni-Provider: webhook
    {"event": {"id", "type", "timestamp"}, "instance": {"id", "channelType"}, "chat": {"id"},
     "sender": {"id", "name", "personId"}, "content": {"text", "emoji"}, "traceId",
     "replyEndpoint": "POST /api/v2/messages/send"}
Resposta: {"reply": "..."} ou {"parts": ["...", "..."]}

Saída ativa (agente -> Omni), para cotação em segundo plano e respostas do vendedor:
    POST <OMNI_URL>/api/v2/messages/send     x-api-key: <OMNI_API_KEY>
    {"instanceId": "<uuid>", "to": "<chat id>", "text": "..."}
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from autoseguro.tools.store import KVStore


class OmniEvent(BaseModel):
    id: str = Field(..., max_length=200)
    type: str = Field(default="message.received", max_length=100)
    timestamp: float | int | None = None


class OmniInstance(BaseModel):
    id: str = Field(..., max_length=100)
    channelType: str = Field(default="", max_length=50)  # noqa: N815 - nome do contrato do Omni


class OmniChat(BaseModel):
    id: str = Field(..., max_length=256)


class OmniSender(BaseModel):
    id: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=256)
    personId: str | None = Field(default=None, max_length=100)  # noqa: N815


class OmniContent(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    emoji: str | None = Field(default=None, max_length=20)


class OmniWebhookPayload(BaseModel):
    event: OmniEvent
    instance: OmniInstance
    chat: OmniChat
    sender: OmniSender = OmniSender()
    content: OmniContent = OmniContent()
    traceId: str | None = Field(default=None, max_length=200)  # noqa: N815
    replyEndpoint: str | None = None  # noqa: N815

    def conversation_id(self) -> str:
        # instância + chat: o mesmo número em duas instâncias são conversas diferentes
        return f"omni:{self.instance.id}:{self.chat.id}"

    def texto_e_tipo(self) -> tuple[str, str]:
        if self.content.text and self.content.text.strip():
            return self.content.text, "text"
        # sem texto: mídia, figurinha ou reação; o agente pede para escrever
        return "[documento] mensagem sem texto", "document"


def rota_key(conversation_ref: str) -> str:
    return f"omni:rota:{conversation_ref}"


class OmniDelivery:
    """Envia mensagens ativas pelo Omni para a conversa certa."""

    def __init__(self, base_url: str, api_key: str, store: KVStore, http: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.store = store
        self.http = http or httpx.AsyncClient(timeout=10)

    async def lembrar_rota(self, conversation_ref: str, payload: OmniWebhookPayload) -> None:
        await self.store.set_json(
            rota_key(conversation_ref), {"instanceId": payload.instance.id, "to": payload.chat.id}
        )

    async def enviar(self, conversation_ref: str, texto: str) -> dict[str, Any] | None:
        rota = await self.store.get_json(rota_key(conversation_ref))
        if not rota:
            return None  # conversa não veio do Omni
        r = await self.http.post(
            f"{self.base_url}/api/v2/messages/send",
            headers={"x-api-key": self.api_key},
            json={"instanceId": rota["instanceId"], "to": rota["to"], "text": texto},
        )
        return {"status": r.status_code}
