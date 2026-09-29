---
paths:
  - "src/autoseguro/**/*.py"
---

# Guardrails

- Texto do lead só entra em LLM, evento, log ou fila depois de `mask()`.
- Nenhum `R$` literal em código fora de `agent/templates.py::brl`.
- Toda resposta ao lead passa pelo nó `saida` (check_output).
- Eventos de trace carregam `conversation_id`, `message_id` e, em cotação, `quote_request_id` e tentativas.
