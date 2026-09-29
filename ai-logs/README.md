# ai-logs

Conversas com IA usadas neste desafio, exportadas sem edição de conteúdo e sanitizadas (segredos e PII mascarados).

| Pasta | Conteúdo |
|---|---|
| `sessions/` | Exports sanitizados (versionados) |
| `raw/` | Exports brutos (ignorados pelo git) |

Como atualizar:
1. Copiar os exports para `ai-logs/raw/` (Claude Code: `~/.claude/projects/<slug>/*.jsonl`; app Claude: Share ou Export da conversa).
2. `uv run python scripts/sanitize_ai_logs.py`
3. `uv run python scripts/sanitize_ai_logs.py --check` (também roda no pre-commit e na CI).

O resumo de cada sessão, com o que foi aceito ou rejeitado, está em `docs/DEVLOG.md`.
