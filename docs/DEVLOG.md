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

## Sessão 1, continuação (29/09/2026): primeiro teste ao vivo (Docker + Groq)
Felipe subiu o `docker compose` no Windows; a IA testou pelo navegador do app Claude (a VM não alcança o `localhost` do Windows).
- Funcionou: os 4 containers conversando, Groq respondendo de verdade, cotação de R$ 209,90 com pro-rata de R$ 13,99 conferida contra a regra, 1 tentativa na /quote, CPF e CEP mascarados no trace e no prompt.
- Problemas achados e corrigidos (com teste de regressão):
  - "o mais completo" virou Completo e "semana que vem" virou hoje: o LLM tinha prioridade sobre a regra. Agora a regra explícita vence e o LLM preenche o que a regra não entende; a regra ignora palavra-chave negada ("o mais barato não serve") e entende "semana que vem" e "mês que vem".
  - Lista de planos repetida quando o lead perguntou preço ou o que é franquia: o LLM marcava `pergunta_planos`. Prompt mais estrito e a lista aparece uma vez só.
  - Saudação duplicada: a frase-ponte do LLM também dizia "Oi". Prompt do redator proíbe cumprimento.
  - Primeiro turno levou 8,9 s (conexão MCP, /planos e primeira chamada ao Groq a frio). O agente agora aquece a conexão MCP e o cache do /planos ao subir.

## Sessão 1, continuação (29/09/2026): reteste ao vivo e etapa 5
- Reteste ao vivo (modo dev): correções confirmadas; a /quote falhou 2 vezes (5xx) e o cliente acertou na 3a tentativa, ao vivo. Achado novo: "isso, pode cotar" não confirmou porque o aceite da regra era descartado quando o LLM não marcava. Corrigido: intenções = LLM + regras.
- Felipe decidiu manter o LangGraph como orquestrador por curiosidade técnica; a IA propôs usar recursos dele na etapa 5 e prototipou antes de codar: `interrupt()` + `aupdate_state(as_node=...)` + `Command(resume=...)` se comportaram como esperado (mensagem do lead durante a pausa não acorda o grafo; retomada não repete o registro do handoff).
- Etapa 5 (ADR 0008): cotação em segundo plano retomando o checkpoint, outbox, humano no circuito, lock no Redis, histórico de checkpoints. Um teste mostrou uma corrida (trace já em handoff antes da entrega no outbox); o teste passou a esperar a entrega.

## Sessão 1, continuação (29/09/2026): etapas 6, 7 e 8
- Omni: a documentação pública não trazia o contrato do provider webhook. A IA clonou o repositório do Omni e leu `webhook-provider.ts`, `types.ts`, `agent-dispatcher.ts` e as rotas do Harness para implementar exatamente o payload, a resposta e o envio ativo. Subir o Omni real no compose foi descartado (Helm, Postgres, NATS e MinIO; sem Docker Hub no ambiente): ficou documentado em `docs/omni.md`, com testes contra um Omni falso fiel ao contrato.
- Simulador: `LeadRoteiro` (reprodutível, base da avaliação) e `LeadFastAgent` (fast-agent + Groq, conversa livre; depende de rede).
- Rastreio: log JSON por linha dos eventos, exportador da execução completa, CEP cifrado com Fernet no checkpoint (`VAULT_KEY`).
- Achado pelo scanner no exportador: ids hexadecimais (`msg_2b2c99598446`) davam falso positivo de CEP e telefone, e a seção "como o lead viu" levava texto bruto. Ids internos passaram a ser ignorados pelo scanner (com teste) e a seção passou a ser mascarada.
- Avaliação na Gold (300 conversas) e estresse (50% de falha): resultados em `docs/avaliacao.md`.
