"""Fila de handoff para o vendedor humano. Só recebe dados mascarados.

Idempotência (auditoria pós-V1): quem registra pode mandar o `handoff_id`; o mesmo id registrado
de novo (retry depois de timeout, fallback do agente) devolve o item já gravado sem duplicar.
Ciclo de vida: pendente -> em_atendimento (vendedor respondeu) -> devolvido (voltou ao bot) ou
encerrado. O status fica num hash à parte; a lista guarda a ordem de chegada.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from autoseguro.guardrails.pii import mask_dict
from autoseguro.tools.store import KVStore

QUEUE_KEY = "handoff:queue"
STATUS_KEY = "handoff:status"
STATUS = ("pendente", "em_atendimento", "devolvido", "encerrado")


class HandoffMotivo(StrEnum):
    RECUSA_REGRA = "recusa_regra"
    COTACAO_INDISPONIVEL = "cotacao_indisponivel"
    PEDIDO_HUMANO = "pedido_humano"
    OBJECAO_PRECO = "objecao_preco"
    FORA_DE_ESCOPO = "fora_de_escopo"
    MIDIA = "midia"
    SEM_PROGRESSO = "sem_progresso"
    PRONTO_PARA_FECHAR = "pronto_para_fechar"


def _item_key(handoff_id: str) -> str:
    return f"handoff:item:{handoff_id}"


class HandoffQueue:
    def __init__(self, store: KVStore) -> None:
        self.store = store

    async def registrar(
        self,
        conversation_id: str,
        motivo: HandoffMotivo | str,
        resumo: str,
        dados: dict[str, Any] | None = None,
        handoff_id: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "handoff_id": handoff_id or f"ho_{uuid.uuid4().hex[:12]}",
            "conversation_id": conversation_id,
            "motivo": str(HandoffMotivo(motivo)),
            "resumo": resumo,
            "dados": dados or {},
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "status": "pendente",
        }
        item = mask_dict(item)  # defesa em profundidade: nada sai daqui sem máscara
        if handoff_id and not await self.store.set_if_absent(
            _item_key(handoff_id), item, ttl_s=30 * 24 * 3600
        ):
            return await self.store.get_json(_item_key(handoff_id)) or item  # já registrado
        await self.store.push(QUEUE_KEY, item)
        return item

    async def atualizar_status(self, handoff_id: str, status: str) -> None:
        if status not in STATUS:
            raise ValueError(f"status inválido: {status}")
        await self.store.hset(
            STATUS_KEY,
            handoff_id,
            {"status": status, "atualizado_em": datetime.now().isoformat(timespec="seconds")},
        )

    async def listar(self, status: str | None = None) -> list[dict[str, Any]]:
        atuais = await self.store.hgetall(STATUS_KEY)
        itens = []
        for item in await self.store.list_all(QUEUE_KEY):
            if (s := atuais.get(item.get("handoff_id"))) is not None:
                item = {**item, "status": s["status"], "atualizado_em": s["atualizado_em"]}
            if status is None or item["status"] == status:
                itens.append(item)
        return itens
