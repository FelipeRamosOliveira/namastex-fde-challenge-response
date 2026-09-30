# ai-logs

Conversas com IA usadas neste desafio, exportadas e sanitizadas (segredos e PII mascarados). O conteúdo não foi editado, com uma exceção: na parte 1 as respostas da IA estão resumidas (motivo abaixo).

| Pasta | Conteúdo |
|---|---|
| `sessions/` | Exports sanitizados (versionados) |
| `raw/` | Exports brutos (ignorados pelo git) |

Sessões:
- `sessions/sessao-2026-09-29-parte-1.md`: 10:33 às 15:47 (análise do desafio, pesquisa, plano, etapas 0 a 8). Mensagens de Felipe na íntegra; respostas da IA como **resumo**, porque o texto original se perdeu numa compactação automática de contexto. Os resumos foram escritos a partir do DEVLOG, do plano, dos ADRs e dos commits.
- `sessions/sessao-2026-09-29-parte-2.md`: 15:47 às 17:44 (segunda revisão independente, documentação, publicação), com as mensagens de Felipe e as respostas da IA na íntegra, e o nome de cada ação. O arquivo termina no meio da última resposta porque o export foi feito durante essa própria resposta.
- Sessão de 30/09 (deploy por terceiro, LLM em texto livre, avaliação com Groq e auditoria independente da V1): resumo em `docs/DEVLOG.md`, sessão 2 e sessão 3.

Os subagentes revisores citados no DEVLOG ("revisão independente") rodaram dentro dessas sessões; o export mostra a chamada e o resultado que voltou para a conversa principal.

A análise da solução pública de outro candidato aparece nos logs de propósito: estudar soluções existentes e as falhas delas fez parte do processo, e vários requisitos desta arquitetura saíram dali (DEVLOG, sessão 1).

O export mostra o que aparece na tela (mensagens, respostas e ações); parâmetros e saídas de ferramentas ficam de fora, porque é onde estariam comandos, conteúdo de arquivos e chaves.

Como atualizar:
1. `uv run python scripts/exportar_conversa.py ~/.claude/projects/<slug>/<sessao>.jsonl ai-logs/raw/<nome>.md`
2. `uv run python scripts/sanitize_ai_logs.py --valores-de .env`
3. `uv run python scripts/sanitize_ai_logs.py --check` (também roda no pre-commit e na CI).

O resumo de cada sessão, com o que foi aceito ou rejeitado, está em `docs/DEVLOG.md`.
