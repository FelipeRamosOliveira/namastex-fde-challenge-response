# ai-logs

Conversas com IA usadas neste desafio, exportadas sem edição de conteúdo e sanitizadas (segredos e PII mascarados).

| Pasta | Conteúdo |
|---|---|
| `sessions/` | Exports sanitizados (versionados) |
| `raw/` | Exports brutos (ignorados pelo git) |

Sessões:
- `sessions/sessao-2026-09-29-parte-1.md`: 10:33 às 15:47 (análise do desafio, pesquisa, plano, etapas 0 a 8). Só as mensagens de Felipe: o arquivo de sessão perdeu esse trecho numa compactação automática de contexto; o que foi feito está em `docs/DEVLOG.md`.
- `sessions/sessao-2026-09-29-parte-2.md`: 15:47 em diante (segunda revisão independente, documentação, publicação), com as respostas do assistente e o nome de cada ação.

O export mostra o que aparece na tela (mensagens, respostas e ações); parâmetros e saídas de ferramentas ficam de fora, porque é onde estariam comandos, conteúdo de arquivos e chaves.

Como atualizar:
1. `uv run python scripts/exportar_conversa.py ~/.claude/projects/<slug>/<sessao>.jsonl ai-logs/raw/<nome>.md`
2. `uv run python scripts/sanitize_ai_logs.py --valores-de .env`
3. `uv run python scripts/sanitize_ai_logs.py --check` (também roda no pre-commit e na CI).

O resumo de cada sessão, com o que foi aceito ou rejeitado, está em `docs/DEVLOG.md`.
