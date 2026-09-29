"""Fila de handoff para o vendedor humano. Só recebe dados mascarados."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from autoseguro.guardrails.pii import mask_dict
from autoseguro.tools.store import KVStore

QUEUE_KEY = "handoff:queue"


class HandoffMotivo(StrEnum):
    RECUSA_REGRA = "recusa_regra"
    COTACAO_INDISPONIVEL = "cotacao_indisponivel"
    PEDIDO_HUMANO = "pedido_humano"
    OBJECAO_PRECO = "objecao_preco"
    FORA_DE_ESCOPO = "fora_de_escopo"
    MIDIA = "midia"
    SEM_PROGRESSO = "sem_progresso"
    PRONTO_PARA_FECHAR = "pronto_para_fechar"


class HandoffQueue:
    def __init__(self, store: KVStore) -> None:
        self.store = store

    async def registrar(
        self,
        conversation_id: str,
        motivo: HandoffMotivo | str,
        resumo: str,
        dados: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = {
            "handoff_id": f"ho_{uuid.uuid4().hex[:12]}",
            "conversation_id": conversation_id,
            "motivo": str(HandoffMotivo(motivo)),
            "resumo": resumo,
            "dados": dados or {},
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "status": "pendente",
        }
        item = mask_dict(item)  # defesa em profundidade: nada sai daqui sem máscara
        await self.store.push(QUEUE_KEY, item)
        return item

    async def listar(self) -> list[dict[str, Any]]:
        return await self.store.list_all(QUEUE_KEY)
