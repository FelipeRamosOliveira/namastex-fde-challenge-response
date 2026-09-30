# AutoSeguro Agent

Agente de WhatsApp que qualifica leads, cota seguro auto na API do desafio e decide quando passar para um humano. Take-home FDE da Namastex.

## Regras de ouro (não negociáveis)
1. **PII**: todo texto passa por `guardrails/pii.py::mask` antes de LLM, log, trace ou fila. Original só no `PiiVault` da conversa.
2. **Valores reais**: preço, franquia, carência e pro-rata saem só da resposta da `POST /quote`, formatados em `agent/templates.py`. LLM nunca escreve valor em R$. `guardrails/output.py` bloqueia qualquer R$ fora da resposta da API.
3. **Omni**: o canal é o Omni (provider webhook). O Omni real e o canal Harness ficam fora do compose; passos em `docs/omni.md`.

## Stack
- Python 3.14 (`.python-version`; testado no 3.14.7; não usar 3.14.0rc*: quebra o pydantic), uv
- LangGraph (orquestração, checkpoint SQLite), FastMCP 4 (ferramentas), FastAPI (API assíncrona), httpx
- Redis (cache e circuit breaker) no Docker; memória nos testes
- fast-agent só como simulador de leads e avaliação (etapa 6), não como orquestrador
- LLM gratuito: Groq principal, OpenRouter reserva (etapa 4)

## Comandos
- Instalar: `uv sync`
- Testes: `uv run pytest` (integração sobe a quote-api original do submódulo)
- Só unitários: `uv run pytest tests/unit`
- Lint: `uv run ruff check src tests && uv run ruff format --check src tests`
- Dados: `uv run python -m autoseguro.data.pipeline silver` e `... gold --quote-url http://localhost:8000`
- Tudo no Docker: `docker compose up --build`
- Docker em modo dev (código montado, recarga automática): `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
- API local: `uv run uvicorn autoseguro.api.app:app --port 8080`

## Estrutura
- `src/autoseguro/guardrails/`: PII (entrada) e checagem de saída
- `src/autoseguro/tools/`: cliente resiliente da /quote, regras do /planos, fila de handoff, servidor MCP
- `src/autoseguro/agent/`: grafo LangGraph, extrator, templates, fachada `AutoSeguroAgent`
- `src/autoseguro/data/`: pipeline Bronze, Silver, Gold
- `vendor/challenge/`: repo original do desafio (submódulo, não editar)
- `docs/adr/`: decisões; `docs/DEVLOG.md`: diário do desenvolvimento com IA; `ai-logs/`: export das sessões
- Limitações conhecidas e próximos passos: README, seção 5.7. Ao corrigir uma delas, atualizar a tabela e o ADR citado.

## Convenções
- Regras detalhadas em `.claude/rules/`.
- Toda decisão de arquitetura nova vira um ADR em `docs/adr/`.
- Ao fim de cada sessão com IA, registrar no `docs/DEVLOG.md` (o que a IA propôs, o que foi aceito ou rejeitado, por quê).
- Todo comportamento novo tem teste. Integração usa a API original, nunca um mock do cálculo de preço.
- Texto para o lead em português, curto, estilo WhatsApp, sem travessão.

## Não fazer
- Não editar nada em `vendor/challenge/`.
- Não commitar `.env`, `ai-logs/raw/` nem dados da Silver.
- Não calcular preço localmente, nem para teste: use a API.
- Não logar texto sem máscara.
