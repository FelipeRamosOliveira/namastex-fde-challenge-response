---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python

- Código de I/O é assíncrono (`async def`, `httpx.AsyncClient`); nada de `requests` ou `time.sleep` em `src/`.
- Configuração só via `autoseguro.config.Settings`; nenhum segredo com valor padrão.
- `ruff check` e `ruff format --check` limpos antes de commit.
- Teste novo para todo comportamento novo; integração em `tests/integration` com marcador `integration`.
