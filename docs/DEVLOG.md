# DEVLOG: desenvolvimento assistido por IA

Diário por sessão. Para cada uma: objetivo, o que a IA propôs, o que foi aceito ou rejeitado, problemas encontrados. O export bruto de cada sessão fica em `ai-logs/sessions/`.

## Sessão 1 (29/09/2026): análise, plano e etapas 0 a 3
**Ferramenta:** Claude (app Claude, sessão de trabalho com acesso a shell na nuvem e à pasta Projetos).

**Antes do código**
- IA clonou o desafio, perfilou o dataset e apontou pegadinhas: preço do vendedor aleatório, timestamps fora de ordem, 11% de leads acima de 75 anos, 21% de veículos com mais de 20 anos.
- IA pesquisou a Namastex (suíte Automagik, Omni) e analisou uma solução pública concorrente, testando o código dela. Achados usados como requisitos: data virando ano do carro, "carro tem 12 anos" virando idade, PII sem máscara indo ao LLM, 37 s de espera no pior caso.
- Felipe definiu a stack e as regras de ouro (PII, valores reais, Omni). IA propôs o papel de cada biblioteca (ADR 0001); aceito.

**Decisões e correções durante o código**
- IA testou a stack antes de escrever: Python 3.14.0rc2 quebrava o pydantic; fixado 3.14.7. `langchain-mcp-adapters` quebra com mcp 2.x; trocado por `fastmcp.Client` direto (ADR 0002).
- Bug achado por teste: o timeout do httpx é por operação, então a resposta lenta não era cortada. Corrigido com `asyncio.timeout` (ADR 0003).
- Teste de vazamento de PII escrito de forma independente do guardrail (regex simples sobre a Bronze), para o guardrail não se autoavaliar.
- Gold gerada com a API real a falha zero, em vez de recalcular preço em Python (regra de ouro 2).
- Docker Hub bloqueado no ambiente de nuvem da IA: `docker compose config` validado, mas o `up` completo roda na máquina do Felipe.

**Resultado:** 86 testes passando (unitários e integração contra a API original), lint limpo.
