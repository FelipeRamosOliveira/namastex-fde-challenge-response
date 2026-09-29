# AutoSeguro Agent

Agente de WhatsApp da seguradora fictícia AutoSeguro (desafio FDE da Namastex): conversa com o lead, qualifica, cota na API do desafio e decide quando passar para um vendedor humano. Não trava e não inventa preço quando a API falha.

> Status: etapas 0 a 3 prontas (fundação, dados, ferramentas MCP resilientes, grafo LangGraph sem LLM). Plano completo em `docs/PLANO.md`.

## Regras de ouro
| Regra | Como é garantida | Prova |
|---|---|---|
| PII protegida | Máscara na entrada (`guardrails/pii.py`) antes de qualquer LLM, log, trace ou fila; checagem na saída | Teste independente: 0 valores da Bronze na Silver e na Gold; trace e fila sem CPF, e-mail ou telefone |
| Valores reais | Preço, franquia, carência e pro-rata saem da resposta da `/quote` por template; guardrail bloqueia R$ que não veio da API | Testes comparam a resposta do agente com a chamada direta à API original |
| Omni | Canal via provider webhook do Omni e canal Harness (etapa 6) | Em andamento |

## Como rodar

### Com Docker (ambiente de simulação completo)
```bash
git clone --recurse-submodules <este-repo> && cd autoseguro-agent
cp .env.example .env          # preencha GROQ_API_KEY (etapa 4) e TRACE_API_KEY
docker compose up --build
```
| Serviço | Porta | O que é |
|---|---|---|
| `quote-api` | 8000 | API **original** do desafio (submódulo, instabilidade padrão de 20% falha e 10% lenta) |
| `mcp-tools` | 8100 | Servidor MCP `autoseguro-tools` (`/mcp`) |
| `agent-api` | 8080 | Agente (`POST /v1/messages`) |
| `redis` | interno | Cache e circuit breaker |

Conversa de exemplo:
```bash
curl -s localhost:8080/v1/messages -H 'content-type: application/json' \
  -d '{"conversation_id":"demo","text":"oi, quero cotar meu Onix 2021"}'
```
Trace (mascarado): `curl localhost:8080/v1/conversations/demo/trace -H "x-api-key: $TRACE_API_KEY"`

Se `CHANNEL_API_KEY` estiver definida no `.env`, envie também `-H "x-channel-key: $CHANNEL_API_KEY"` em `/v1/messages`.

### Sem Docker
```bash
uv sync
(cd vendor/challenge/quote-service && uv run uvicorn app.main:app --port 8000) &
uv run uvicorn autoseguro.api.app:app --port 8080     # sobe as ferramentas MCP em processo
```

### Testes
```bash
uv run pytest                  # unitários + integração contra a quote-api original
uv run pytest tests/unit       # só unitários
uv run ruff check src tests
```

## Arquitetura
```
Lead -> (Omni, etapa 6) -> FastAPI /v1/messages -> LangGraph
  entrada (máscara PII) -> decidir (extrai, pré-valida regras) -> cotar (MCP) | handoff (MCP)
  -> saida (guardrail de PII e de valores) -> lead

MCP autoseguro-tools: consultar_planos, pre_validar, cotar, registrar_handoff, status_cotacao
Cotar: timeout 2,5 s, hedging em 1,2 s, retry com jitter, circuit breaker, cache da resposta real
Fachada: lock por conversa, máscara antes do grafo, id opaco, idempotência por message_id
```

## Decisões (resumo; detalhes em `docs/adr/`)
| # | Decisão | Por quê |
|---|---|---|
| 0001 | LangGraph orquestra; FastMCP expõe ferramentas; fast-agent só simula leads | Um único dono do estado da conversa |
| 0002 | Grafo chama MCP pelo `fastmcp.Client` | `langchain-mcp-adapters` quebra com mcp 2.x |
| 0003 | Timeout curto + hedging + retry + circuit breaker + cache | Não esperar os 8 s da chamada lenta; p95 abaixo de 3 s com a instabilidade padrão |
| 0004 | Máscara com tokens estáveis e vault por conversa | LLM e logs nunca veem o dado; o CEP real só é usado na cotação |
| 0005 | Valores só via template a partir da API | Preço inventado é impossível por construção e bloqueado na saída |
| 0006 | Dataset em Bronze, Silver e Gold | Gold com respostas reais da API vira base de avaliação |

## Quando o agente passa para um humano
| Motivo | Quando |
|---|---|
| `recusa_regra` | Pré-validação ou 422: idade acima de 75, veículo com mais de 20 anos |
| `cotacao_indisponivel` | `/quote` indisponível depois das tentativas (etapa 5: nova tentativa em segundo plano antes) |
| `pedido_humano` | Lead pede atendente |
| `objecao_preco` | Segunda objeção de preço, ou objeção citando concorrente (a primeira recebe a cotação real do Essencial) |
| `fora_de_escopo` | Sinistro, cancelamento, outro produto |
| `midia` | Segunda mídia depois do pedido para escrever |
| `sem_progresso` | 6 turnos sem dado novo |
| `pronto_para_fechar` | Lead aceita a proposta: emissão de apólice e boleto é humana, como no dataset |

## Rastreio
Cada turno gera eventos com `event_id`, `conversation_id` (opaco: hash do id do canal) e `message_id`: `message_in` (com os tipos de PII detectados), `extracao`, `pre_validacao`, `cotacao` (com `quote_request_id`, `quote_id`, tentativas, status HTTP, latência, hedge e cache), `handoff` e `message_out`.

## Dados
```bash
uv run python -m autoseguro.data.pipeline silver
uv run python -m autoseguro.data.pipeline gold --quote-url http://localhost:8000   # API com QUOTE_FAILURE_RATE=0
```
A Gold (`data/gold/cases.jsonl`, 300 casos) é versionada: é pequena, mascarada e usa CEP generalizado.

## Desenvolvimento assistido por IA
- `CLAUDE.md` e `.claude/`: contexto, regras, hooks e subagentes de revisão.
- `docs/DEVLOG.md`: o que a IA propôs, o que foi aceito ou rejeitado, por quê.
- `ai-logs/`: export das sessões, sanitizado por `scripts/sanitize_ai_logs.py` (checado no pre-commit e na CI).
