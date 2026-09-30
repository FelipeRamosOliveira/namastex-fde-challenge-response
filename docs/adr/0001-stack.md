# ADR 0001: Stack e papel de cada biblioteca

- Status: aceito (29/09/2026)

## Contexto
Requisitos do Felipe: Python 3.14, LLM com endpoint gratuito, Docker como simulação, fast-agent e FastMCP, LangGraph, assíncrono, cache. LangGraph e fast-agent orquestram agentes; usar os dois como cérebro criaria duas fontes de verdade para o estado da conversa.

## Decisão
| Peça | Papel |
|---|---|
| LangGraph | Orquestração do atendimento (máquina de estados, checkpoint por conversa) |
| FastMCP | Servidor `autoseguro-tools` com as ferramentas de negócio |
| FastAPI + httpx | Porta de entrada e chamadas assíncronas |
| fast-agent | Simulador de leads e avaliação (etapa 6) |
| Redis | Cache e circuit breaker compartilhados |
| Groq (reserva OpenRouter) | LLM gratuito (etapa 4) |

A cotação é chamada por um nó determinístico do grafo, não por escolha do LLM.

## Alternativas consideradas
- **fast-agent como orquestrador:** descartado. Seria um segundo dono do estado da conversa; ficou só como simulador de leads.
- **Orquestração só em código (sem framework):** mais simples, mas o LangGraph já traz checkpoint por conversa, `interrupt()` para o humano e histórico de estados, usados no ADR 0008. Felipe também quis explorar o LangGraph a fundo.
- **`langchain-mcp-adapters` para ligar grafo e MCP:** descartado no ADR 0002.

## Consequências
- Python 3.14, nunca rc: o 3.14.0rc2 quebra o pydantic (testado). O `.python-version` foi de `3.14.7` para `3.14` na sessão 2, porque `uv` antigo não conhecia o 3.14.7; um `uv` antigo ainda pode escolher o rc2 (solução na tabela de problemas comuns do README).
- Testado em 29/09/2026: LangGraph 1.2.12, FastMCP 4.0.5, fast-agent-mcp 0.10.39 importam no 3.14.7.
- Custo: dois processos (agente e `mcp-tools`) e uma dependência a mais (LangGraph) para um fluxo que caberia numa máquina de estados simples.
