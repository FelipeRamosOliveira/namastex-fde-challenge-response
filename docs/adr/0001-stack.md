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

## Consequências
- Python fixado em 3.14.7: o 3.14.0rc2 quebra o pydantic (testado).
- Testado em 29/09/2026: LangGraph 1.2.12, FastMCP 4.0.5, fast-agent-mcp 0.10.39 importam no 3.14.7.
