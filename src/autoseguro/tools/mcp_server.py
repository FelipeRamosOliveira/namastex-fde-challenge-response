"""Servidor MCP `autoseguro-tools` (FastMCP).

Ferramentas expostas ao agente (e a qualquer cliente MCP, como fast-agent ou Omni):
- consultar_planos: planos e regras vindos do GET /planos
- pre_validar: aplica as regras de aceitação antes de cotar
- cotar: POST /quote com resiliência e cache (valores sempre da API)
- registrar_handoff: coloca a conversa na fila do vendedor (dados mascarados)

Rodar como servidor HTTP:  uv run python -m autoseguro.tools.mcp_server
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP
from pydantic import Field

from autoseguro.config import Settings, get_settings
from autoseguro.tools.handoff import HandoffMotivo, HandoffQueue
from autoseguro.tools.quote_client import QuoteClient
from autoseguro.tools.rules import PlanosRepository
from autoseguro.tools.store import KVStore, make_store


@dataclass
class Services:
    quote: QuoteClient
    planos: PlanosRepository
    handoff: HandoffQueue
    store: KVStore

    @classmethod
    def from_settings(cls, s: Settings, store: KVStore | None = None, http: httpx.AsyncClient | None = None):
        store = store or make_store(s.redis_url)
        http = http or httpx.AsyncClient(base_url=s.quote_api_url)
        return cls(
            QuoteClient(s, store, http), PlanosRepository(http, s.planos_ttl_s), HandoffQueue(store), store
        )


def build_server(services: Services) -> FastMCP:
    mcp = FastMCP(
        "autoseguro-tools",
        instructions="Ferramentas de cotação da AutoSeguro. Preço só vem da ferramenta `cotar`.",
    )

    @mcp.tool
    async def consultar_planos() -> dict[str, Any]:
        """Lista os planos (id, nome, coberturas, franquia) e as regras de carência e pro-rata."""
        return {"planos": await services.planos.resumo(), "regras": await services.planos.regras_texto()}

    @mcp.tool
    async def pre_validar(
        idade: Annotated[int | None, Field(ge=0, le=130)] = None,
        veiculo_ano: Annotated[int | None, Field(ge=1950, le=2100)] = None,
        plano_id: str | None = None,
    ) -> dict[str, Any]:
        """Checa as regras de aceitação (idade do condutor, idade do veículo, plano) sem chamar /quote."""
        return asdict(await services.planos.pre_validar(idade, veiculo_ano, plano_id))

    @mcp.tool
    async def cotar(
        plano_id: str,
        idade: Annotated[int, Field(ge=0, le=130)],
        veiculo_ano: Annotated[int, Field(ge=1950, le=2100)],
        cep: str | None = None,
        data_inicio: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
    ) -> dict[str, Any]:
        """Cota o seguro na API da AutoSeguro com retry, hedging, circuit breaker e cache."""
        payload = {
            "plano_id": plano_id,
            "idade": idade,
            "veiculo_ano": veiculo_ano,
            "cep": cep,
            "data_inicio": data_inicio,
        }
        return (await services.quote.cotar(payload)).to_dict()

    @mcp.tool
    async def registrar_handoff(
        conversation_id: str, motivo: HandoffMotivo, resumo: str, dados: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Encaminha a conversa para um vendedor humano com um resumo mascarado."""
        return await services.handoff.registrar(conversation_id, motivo, resumo, dados)

    @mcp.tool
    async def status_cotacao() -> dict[str, Any]:
        """Saúde da API de cotação e estado do circuit breaker."""
        return {
            "api_ok": await services.quote.health(),
            "circuit_breaker": await services.quote.breaker.state(),
        }

    return mcp


def main() -> None:
    s = get_settings()
    build_server(Services.from_settings(s)).run(transport="http", host="0.0.0.0", port=8100)  # noqa: S104


if __name__ == "__main__":
    main()
