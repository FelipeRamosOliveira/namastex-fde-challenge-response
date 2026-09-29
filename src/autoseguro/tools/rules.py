"""Regras de aceitação lidas do GET /planos da API do desafio (fonte única da verdade).

Serve para pré-validar antes de cotar (economiza chamada à API instável) e para
explicar planos e regras ao lead. NUNCA calcula preço: preço só vem do POST /quote.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx


@dataclass
class PreValidacao:
    ok: bool
    regra: str | None = None
    motivo: str | None = None


class PlanosRepository:
    def __init__(self, http: httpx.AsyncClient, ttl_s: int = 3600) -> None:
        self.http, self.ttl_s = http, ttl_s
        self._cache: dict[str, Any] | None = None
        self._at = 0.0

    async def get(self) -> dict[str, Any]:
        if self._cache is None or time.monotonic() - self._at > self.ttl_s:
            r = await self.http.get("/planos", timeout=5)
            r.raise_for_status()
            self._cache, self._at = r.json(), time.monotonic()
        return self._cache

    async def plano_ids(self) -> list[str]:
        return [p["id"] for p in (await self.get())["planos"]]

    async def resumo(self) -> list[dict[str, Any]]:
        """Resumo dos planos para mostrar ao lead (sem preço: o preço depende do perfil)."""
        return [
            {"id": p["id"], "nome": p["nome"], "coberturas": p["coberturas"], "franquia": p["franquia"]}
            for p in (await self.get())["planos"]
        ]

    async def pre_validar(
        self,
        idade: int | None = None,
        veiculo_ano: int | None = None,
        plano_id: str | None = None,
        hoje: date | None = None,
    ) -> PreValidacao:
        dados = await self.get()
        regras = dados["regras"]
        hoje = hoje or date.today()
        if plano_id is not None and plano_id not in [p["id"] for p in dados["planos"]]:
            return PreValidacao(False, "plano", f"Plano '{plano_id}' inexistente.")
        if idade is not None:
            faixa = next(
                (f for f in regras["faixa_etaria"] if f["idade_min"] <= idade <= f["idade_max"]), None
            )
            if faixa is None:
                return PreValidacao(False, "faixa_etaria", "Idade fora das faixas aceitas.")
            if faixa.get("recusar"):
                return PreValidacao(False, "faixa_etaria", faixa.get("motivo"))
        if veiculo_ano is not None:
            anos = hoje.year - veiculo_ano
            faixa = next((f for f in regras["idade_veiculo"] if f["anos_min"] <= anos <= f["anos_max"]), None)
            if faixa is None:
                return PreValidacao(False, "idade_veiculo", "Idade do veiculo fora das faixas aceitas.")
            if faixa.get("recusar"):
                return PreValidacao(False, "idade_veiculo", faixa.get("motivo"))
        return PreValidacao(True)

    async def regras_texto(self) -> dict[str, Any]:
        r = (await self.get())["regras"]
        return {
            "carencia_dias": r["carencia"]["dias"],
            "carencia_coberturas": r["carencia"]["coberturas_com_carencia"],
            "entrada_meio_mes": r["entrada_meio_mes"]["_obs"],
        }
