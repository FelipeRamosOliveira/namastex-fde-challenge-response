# ADR 0002: LangGraph chama as ferramentas MCP pelo fastmcp.Client

- Status: aceito (29/09/2026)

## Contexto
O `langchain-mcp-adapters` 0.3.1 falha ao importar com `mcp` 2.x (dependência do FastMCP 4): `cannot import name 'RequestContext'`.

## Decisão
Os nós do grafo usam `ToolGateway`, um invólucro fino sobre `fastmcp.Client`. Com `MCP_URL`, fala HTTP com o container `mcp-tools`; sem, sobe o servidor em processo (testes e desenvolvimento).

## Consequências
- Menos uma dependência; o contrato das ferramentas fica explícito no gateway.
- As mesmas ferramentas servem ao Claude Code (`.mcp.json`), ao fast-agent e ao Omni.
