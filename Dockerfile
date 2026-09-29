# Imagem única do agente: serve a API (agent-api) e o servidor MCP (mcp-tools).
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app

# Dependências primeiro (cache de camada)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data/runtime && chown -R app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080 8100
CMD ["uvicorn", "autoseguro.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
