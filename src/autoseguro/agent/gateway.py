"""Acesso às ferramentas MCP a partir do grafo.

Os nós do LangGraph chamam as ferramentas direto pelo `fastmcp.Client` (o
langchain-mcp-adapters ainda não é compatível com mcp 2.x; ver ADR 0002).
Com MCP_URL definido, fala com o servidor HTTP; sem, sobe o servidor em processo.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Client, FastMCP


class ToolGateway:
    def __init__(self, target: str | FastMCP) -> None:
        self._client = Client(target)

    async def __aenter__(self) -> ToolGateway:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    async def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        res = await self._client.call_tool(name, {k: v for k, v in args.items() if v is not None})
        return res.data if res.data is not None else (res.structured_content or {})

    async def consultar_planos(self) -> dict[str, Any]:
        return await self._call("consultar_planos", {})

    async def pre_validar(self, **kw: Any) -> dict[str, Any]:
        return await self._call("pre_validar", kw)

    async def cotar(self, **kw: Any) -> dict[str, Any]:
        return await self._call("cotar", kw)

    async def registrar_handoff(self, **kw: Any) -> dict[str, Any]:
        return await self._call("registrar_handoff", kw)
