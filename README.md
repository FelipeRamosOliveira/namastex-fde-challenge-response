# AutoSeguro Agent

Agente de WhatsApp da seguradora fictícia AutoSeguro (desafio FDE da Namastex): conversa com o lead, qualifica, cota na API do desafio e decide quando passar para um vendedor humano. Não trava e não inventa preço quando a API falha.

> Status: etapas 0 a 8 prontas. Plano em `docs/PLANO.md`.

## Resultado em uma tabela
Avaliação com 300 conversas da Gold contra a quote-api original, instabilidade padrão (detalhes em `docs/avaliacao.md`):

| Critério do desafio | Resultado |
|---|---|
| Funciona de ponta a ponta | 210/210 leads elegíveis chegaram à cotação; preço igual ao da API em 284/284 |
| O que faz quando a /quote falha | Timeout curto + hedging + retry + circuit breaker; se ainda falhar, avisa o lead e tenta de novo em segundo plano. Com 50% de falha: 72/72 cotados, 18 em segundo plano, 0 preço inventado, 0 conversa sem desfecho |
| Critério de handoff explícito | 8 motivos em código (tabela abaixo); 258/258 coerentes com o caso |
| Rastreio | Evento com id e status para cada mensagem, cotação e tentativa; checkpoints do LangGraph; log de execução completa em `docs/execucao/` |
| Dados sensíveis | Máscara antes de LLM, log, trace e fila; 0 PII em 26.470 mensagens da Silver e nas respostas; CEP cifrado no checkpoint (chave com rotação); texto do vendedor passa pelo guardrail |
| Uso de IA | `docs/DEVLOG.md` (o que a IA propôs e o que foi aceito ou rejeitado) e `ai-logs/` |

## Regras de ouro
| Regra | Como é garantida | Prova |
|---|---|---|
| PII protegida | Máscara na entrada (`guardrails/pii.py`) antes de qualquer LLM, log, trace ou fila; checagem na saída | Teste independente: 0 valores da Bronze na Silver e na Gold; trace e fila sem CPF, e-mail ou telefone |
| Valores reais | Preço, franquia, carência e pro-rata saem da resposta da `/quote` por template; guardrail bloqueia R$ que não veio da API | Testes comparam a resposta do agente com a chamada direta à API original |
| Omni | O agente é um provider `webhook` do Omni; mensagens ativas voltam por `/api/v2/messages/send` (`docs/omni.md`) | Testes com um Omni falso que segue o contrato do código-fonte do Omni |

## Como rodar

### Com Docker (ambiente de simulação completo)
```bash
git clone --recurse-submodules <este-repo> && cd autoseguro-agent
cp .env.example .env          # preencha GROQ_API_KEY, TRACE_API_KEY, CHANNEL_API_KEY e VAULT_KEY
                              # (no Docker o agente não sobe sem CHANNEL_API_KEY e VAULT_KEY)
docker compose up --build
```
| Serviço | Porta | O que é |
|---|---|---|
| `quote-api` | 8000 | API **original** do desafio (submódulo, instabilidade padrão de 20% falha e 10% lenta) |
| `mcp-tools` | 8100 | Servidor MCP `autoseguro-tools` (`/mcp`) |
| `agent-api` | 8080 | Agente (`POST /v1/messages`) |
| `redis` | interno | Cache e circuit breaker |

#### Modo desenvolvimento (sem rebuild a cada mudança)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
A pasta `src/` é montada nos containers `agent-api` e `mcp-tools`, que recarregam sozinhos quando um arquivo muda (cerca de 1 s). Rebuild (`... up -d --build`) só quando mudarem `pyproject.toml`, `uv.lock` ou o `Dockerfile`.

Conversa de exemplo:
```bash
curl -s localhost:8080/v1/messages -H 'content-type: application/json' -H "x-channel-key: $CHANNEL_API_KEY" \
  -d '{"conversation_id":"demo","text":"oi, quero cotar meu Onix 2021"}'
```
Trace (mascarado): `curl localhost:8080/v1/conversations/demo/trace -H "x-api-key: $TRACE_API_KEY"`

Fora do Docker, sem `CHANNEL_API_KEY`, o canal fica aberto (só para desenvolvimento). Conversas do Omni (`omni:...`) só entram por `/omni/webhook`.

### Sem Docker
```bash
uv sync
(cd vendor/challenge/quote-service && uv run uvicorn app.main:app --port 8000) &
uv run uvicorn autoseguro.api.app:app --port 8080     # sobe as ferramentas MCP em processo
```

### Testes
```bash
uv run pytest                  # unitários + integração contra a quote-api original (LLM simulado)
uv run pytest tests/unit       # só unitários
uv run pytest -m llm tests/live   # AO VIVO com o Groq (precisa de GROQ_API_KEY)
uv run python scripts/smoke_llm.py   # conversa de demonstração com o Groq de verdade
uv run ruff check src tests
```

## Arquitetura
```
Lead -> (Omni, etapa 6) -> FastAPI /v1/messages -> LangGraph
  entrada (máscara PII) -> decidir (extrai com LLM validado ou regras, pré-valida) -> cotar (MCP) | handoff (MCP)
  -> saida (frase-ponte do LLM, se couber; guardrail de PII e de valores) -> lead

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
| 0008 | Cotação em segundo plano retomando o checkpoint; humano no circuito com `interrupt()` | Queda transitória não vira handoff; vendedor responde, devolve ao bot ou encerra |
| 0007 | LLM (Groq gpt-oss-20b, reserva OpenRouter) só interpreta e redige frase-ponte sem números | Entende texto livre sem poder decidir fluxo nem preço; falha do LLM cai nas regras |

## Quando o agente passa para um humano
| Motivo | Quando |
|---|---|
| `recusa_regra` | Pré-validação ou 422: idade acima de 75, veículo com mais de 20 anos |
| `cotacao_indisponivel` | `/quote` segue fora depois das tentativas rápidas **e** das novas tentativas em segundo plano (5, 20 e 60 s); até lá o lead é avisado e recebe a cotação assim que sair |
| `pedido_humano` | Lead pede atendente |
| `objecao_preco` | Segunda objeção de preço, ou objeção citando concorrente (a primeira recebe a cotação real do Essencial) |
| `fora_de_escopo` | Sinistro, cancelamento, outro produto |
| `midia` | Segunda mídia depois do pedido para escrever |
| `sem_progresso` | 6 turnos sem dado novo |
| `pronto_para_fechar` | Lead aceita a proposta: emissão de apólice e boleto é humana, como no dataset |

## Endpoints
| Rota | Quem usa | Chave |
|---|---|---|
| `POST /v1/messages` | Canal genérico (ids `omni:` recusados) | `x-channel-key` (`CHANNEL_API_KEY`) |
| `GET /v1/conversations/{id}/outbox` | Canal: mensagens ativas (cotação em segundo plano, humano) | idem |
| `GET /v1/handoffs` | Vendedor: fila mascarada | `x-api-key` (`TRACE_API_KEY`) |
| `POST /v1/conversations/{id}/operador` | Vendedor: `responder` (passa pelo guardrail), `devolver`, `encerrar` | idem |
| `GET /v1/conversations/{id}/trace` | Rastreio mascarado | idem |
| `GET /v1/conversations/{id}/historico` | Checkpoints do LangGraph (viagem no tempo) | idem |
| `POST /omni/webhook` | Omni (provider webhook) | `Authorization: Bearer` (`OMNI_PROVIDER_KEY`) |

Nas rotas do vendedor e de rastreio, `{id}` pode ser o `conversation_ref` (`conv_...`) que aparece na fila: o telefone não precisa ir na URL.

## Log de execução completa
`docs/execucao/feliz.md` (conversa do início ao fim até fechar) e `docs/execucao/resiliencia.md` (a /quote cai depois da confirmação; o lead é avisado e recebe a cotação em segundo plano quando ela volta). Os `.jsonl` ao lado têm os eventos crus. Regerar: `uv run python scripts/exportar_execucao.py`.

Em produção, cada evento também sai no log do container como JSON por linha (`docker compose logs agent-api`).

## Simulador e avaliação
```bash
uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 300          # leads por roteiro
uv run --extra sim python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 5 --lead fastagent  # leads com LLM (fast-agent + Groq)
```

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
