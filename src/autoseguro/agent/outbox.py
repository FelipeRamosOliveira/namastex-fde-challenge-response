"""Mensagens ativas para o lead (fora da resposta síncrona): cotação que saiu em segundo
plano, resposta do atendente, devolução da conversa ao bot.

Guarda em uma lista por conversa (KVStore/Redis) e, se OUTBOUND_WEBHOOK_URL estiver
configurada, entrega no canal (ex.: Omni). O canal consulta `GET /v1/conversations/{id}/outbox`
quando não há webhook.

Reentrega (auditoria pós-V1): se o Omni ou o webhook falhar, o item vai para uma fila de
reentrega (hash no KVStore) e o evento `entrega_falhou` sai no log de rastreio. `reentregar`
tenta de novo com backoff só nos destinos que falharam; depois da última tentativa, desiste com
o evento `entrega_desistiu` (a mensagem continua no outbox para o canal buscar).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from autoseguro.tools.store import KVStore

REENTREGA_KEY = "outbox:reentrega"
BACKOFF_S = (10.0, 30.0, 120.0, 300.0, 900.0)  # depois da última, desiste
trace_log = logging.getLogger("autoseguro.trace")


def _evento(tipo: str, **dados: Any) -> None:
    ev = {"event_id": f"evt_{uuid.uuid4().hex[:12]}", "ts": datetime.now().isoformat(timespec="milliseconds")}
    trace_log.info(json.dumps({**ev, "type": tipo, **dados}, ensure_ascii=False, default=str))


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

    async def _omni(self, ref: str, texto: str) -> bool | None:
        """True entregue, False falhou, None não se aplica (conversa não veio do Omni)."""
        if self.omni is None:
            return None
        try:
            res = await self.omni.enviar(ref, texto)
        except httpx.HTTPError:
            return False
        return None if res is None else res["status"] < 300

    async def _webhook(self, item: dict[str, Any], conversation_id: str | None) -> bool | None:
        if not self.webhook_url:
            return None
        try:
            r = await self.http.post(self.webhook_url, json={**item, "conversation_id": conversation_id})
        except httpx.HTTPError:
            return False
        return r.status_code < 300

    async def push(
        self,
        conversation_ref: str,
        texto: str,
        origem: str,
        conversation_id: str | None = None,
        stage: str | None = None,
        motivo_handoff: str | None = None,
    ) -> dict[str, Any]:
        """Entrega `texto` ao canal e guarda uma cópia mascarada.

        O que fica guardado não tem o id do canal (no Omni é o telefone). O texto chega aqui já
        aprovado pelo guardrail de saída (bot e vendedor), então não carrega PII do lead nem R$ fora
        da API. O id do canal só vai no POST ao webhook, que precisa dele para rotear."""
        item = {
            "message_id": f"out_{uuid.uuid4().hex[:12]}",
            "conversation_ref": conversation_ref,
            "texto": texto,
            "origem": origem,  # agente | humano
            "stage": stage,
            "motivo_handoff": motivo_handoff,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "entregue_webhook": False,
            "entregue_omni": False,
        }
        omni = await self._omni(conversation_ref, texto)  # conversa que veio do Omni volta pelo Omni
        item["entregue_omni"] = bool(omni)
        webhook = await self._webhook(item, conversation_id)
        item["entregue_webhook"] = bool(webhook)
        await self.store.push(f"outbox:{conversation_ref}", item)
        falhou = [d for d, ok in (("omni", omni), ("webhook", webhook)) if ok is False]
        if falhou:
            await self._agendar(item, falhou, tentativas=1)
        return item

    async def _agendar(self, item: dict[str, Any], destinos: list[str], tentativas: int) -> None:
        _evento(
            "entrega_falhou",
            conversation_id=item["conversation_ref"],
            out_message_id=item["message_id"],
            destinos=destinos,
            tentativa=tentativas,
        )
        if tentativas > len(BACKOFF_S):
            await self.store.hdel(REENTREGA_KEY, item["message_id"])
            _evento(
                "entrega_desistiu",
                conversation_id=item["conversation_ref"],
                out_message_id=item["message_id"],
                destinos=destinos,
            )
            return
        pendente = {
            "item": item,
            "destinos": destinos,
            "tentativas": tentativas,
            "proxima": time.time() + BACKOFF_S[tentativas - 1],
        }
        await self.store.hset(REENTREGA_KEY, item["message_id"], pendente)

    async def reentregar(
        self, canal: Callable[[str], Awaitable[str | None]], agora: float | None = None
    ) -> int:
        """Tenta de novo o que venceu. `canal(ref)` devolve o id do canal para o webhook.
        Devolve quantas mensagens foram entregues nesta passada."""
        agora = time.time() if agora is None else agora
        entregues = 0
        for mid, p in (await self.store.hgetall(REENTREGA_KEY)).items():
            if p["proxima"] > agora:
                continue
            item, ref = p["item"], p["item"]["conversation_ref"]
            falhou = []
            for destino in p["destinos"]:
                if destino == "omni":
                    ok = await self._omni(ref, item["texto"])
                else:
                    ok = await self._webhook(item, await canal(ref))
                if ok is False:
                    falhou.append(destino)
            if falhou:
                await self._agendar(item, falhou, p["tentativas"] + 1)
            else:
                await self.store.hdel(REENTREGA_KEY, mid)
                entregues += 1
                _evento(
                    "entrega_reentregue",
                    conversation_id=ref,
                    out_message_id=mid,
                    destinos=p["destinos"],
                    tentativa=p["tentativas"] + 1,
                )
        return entregues

    async def listar(self, conversation_ref: str, depois_de: int = 0) -> list[dict[str, Any]]:
        return (await self.store.list_all(f"outbox:{conversation_ref}"))[depois_de:]
