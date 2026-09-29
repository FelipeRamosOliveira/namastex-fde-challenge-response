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

**Revisão independente (subagente que não escreveu o código)**
Achou 12 problemas, 10 reproduzidos. Todos corrigidos com teste de regressão:
- Crítico: mensagens em rajada na mesma conversa perdiam dados (último a gravar vence). Lock por conversa.
- CEP usado na cotação diferente do mostrado na confirmação quando a mensagem tinha dois CEPs.
- Telefone com o 9 separado, fixo sem DDD, CPF sem pontuação com dígito inválido e nome declarado passavam sem máscara.
- Id da conversa (telefone no Omni) era mascarado na fila, quebrando o roteamento, e ficava exposto nos eventos. Id opaco.
- Extração: "nasci em 1985" virava ano do carro; "5 anos de carteira" virava idade; "o mais completo" virava Completo.
- Idade fora da faixa derrubava o turno (HTTP 500); mídia enviada por `message_type` image/document não era detectada.
- Data de início vencida era cotada ao retomar no dia seguinte; mudança de dado depois da cotação mantinha a cotação velha.
- 200 com corpo inválido virava cotação e ia para o cache; meia-abertura do breaker deixava passar todo mundo.
- API: chave do canal opcional, `compare_digest`, limite do `message_id`, idempotência por `message_id`, porta do MCP só local.
- Achado por um teste novo: a saudação caía no fallback porque o guardrail lia "aqui é o assistente" como nome. Regex corrigida e teste que passa todos os textos fixos pelo guardrail.

**Resultado:** 120 testes passando (unitários e integração contra a API original), lint limpo.

## Sessão 1, continuação (29/09/2026): etapa 4
- A chave do Groq tinha sido colada na linha `OPENROUTER_API_KEY` do `.env`; a IA detectou pelo prefixo `gsk_` (sem exibir o valor) e moveu para `GROQ_API_KEY`.
- O Groq e o OpenRouter são bloqueados pela política de rede tanto na nuvem da IA quanto na VM do computador. Decisão: desenvolver com um Groq falso (`tests/unit/fake_llm.py`) e deixar teste ao vivo e smoke para rodar na máquina do Felipe.
- Modelo: a IA consultou a documentação atual do Groq e trocou `llama-3.3-70b-versatile` por `openai/gpt-oss-20b`, que tem structured outputs estrito (ADR 0007).
- Proposta aceita: LLM só como intérprete (extração validada) e redator de frase-ponte sem números; decisões e valores continuam no código.
- Detalhe do Python 3.14: o `ruff format` reescreveu `except (A, B):` como `except A, B:` (PEP 758, válido no 3.14).
