# DEVLOG: desenvolvimento assistido por IA

Diário por sessão. Para cada uma: objetivo, o que a IA propôs, o que foi aceito ou rejeitado, problemas encontrados. O export bruto de cada sessão fica em `ai-logs/sessions/`.

## Onde decidi diferente da IA ou mudei o rumo
Resumo das decisões que foram minhas, não da IA, com o trecho correspondente nos logs ou nesta página.
- **Stack e regras de ouro** (PII, valores reais, Omni): definidas por mim antes do código; a IA propôs o papel de cada biblioteca dentro delas (ADR 0001). Log: parte 1, pedido do plano.
- **Estudar a solução pública de outro candidato antes de desenhar a minha:** pedi a análise da arquitetura, da stack, dos dados e de como o segredo do LLM era guardado. As falhas encontradas viraram requisitos (espera de 37 s, PII indo ao LLM, data virando ano do carro). Log: parte 1 e parte 2 (17:20 e 17:24).
- **Omni no canal:** depois da pesquisa sobre a Namastex, propus usar o Omni, uma ferramenta da própria empresa, como canal. Log: parte 1.
- **Manter o LangGraph** quando a IA comentou alternativas de orquestração, para explorar a ferramenta a fundo. A IA passou a usar `interrupt()` e checkpoints na etapa 5 (ADR 0008). Log: parte 1.
- **Modo dev no Docker:** pedi para não reconstruir a imagem a cada mudança (`docker-compose.dev.yml`). Log: parte 1.
- **Healthchecks do compose:** corrigi eu mesmo o `docker-compose.yml` quando o agente subia antes do MCP (sessão 1, etapas 6 a 8).
- **README:** rejeitei a primeira versão por ser longa demais para um deploy rápido e defini a estrutura (ficha e guia curtos primeiro, detalhes depois). Log: parte 2 (16:29 e 16:56).
- **ai-logs:** cobrei a IA quando o export escondia demais as respostas dela ("parece que estou falando sozinho"). Log: parte 2 (17:44).
- **Teste de deploy por terceiro** e pedido de fluxo de conversa mais natural, que geraram as correções da sessão 2.
- **Depois da auditoria da V1 (sessão 3):** preferi não mexer no código perto da entrega e documentar as limitações encontradas (README 5.7), em vez de aplicar correções sem tempo de teste.
- **Sessão 4:** com tempo para testar, pedi para corrigir os achados sem mexer no que já funcionava; a tabela 5.7 passou a mostrar a situação de cada um.

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
- Teste ao vivo da etapa 5 no Docker (via navegador do app): handoff pausado, mensagem do lead durante a pausa, vendedor respondendo, devolução ao bot retomando no dado que faltava, segundo "devolver" recusado (409), 30 checkpoints no histórico, CPF mascarado na fila e no trace. Ajuste: a frase-ponte do LLM saía antes da saudação num "oi" simples; removida no primeiro turno.
- Felipe corrigiu o `docker-compose.yml` (healthchecks e `agent-api` esperando o `mcp-tools` ficar saudável): o agente caía ao subir antes do MCP. Commit dele trazido para o repositório.
- A segunda revisão independente (etapas 5 a 8) foi interrompida pelo Felipe antes de rodar; depois ele pediu para executar.

## Sessão 1, continuação (29/09/2026): segunda revisão independente (etapas 5 a 8)
Um agente revisor separado, sem ter visto o código ser escrito, leu os commits das etapas 5 a 8 e reproduziu os problemas com scripts. Encontrou 9; todos corrigidos, cada um com teste de regressão em `tests/integration/test_revisao_etapas5a8.py` (conferido que o teste falha sem a correção):
1. **Canal aberto**: sem `CHANNEL_API_KEY`, qualquer um mandava mensagem com o id de uma conversa do Omni (`omni:<instância>:<telefone>`) e lia o outbox dela. Agora ids `omni:` só entram pelo webhook autenticado, e no Docker o agente não sobe sem `CHANNEL_API_KEY` e `VAULT_KEY` (`EXIGIR_SEGREDOS=true`).
2. **Correção ignorada durante a espera**: se o lead trocava o plano enquanto a cotação estava em segundo plano, a troca era descartada e ele recebia o preço do plano antigo (valor real da API, mas do plano errado). Agora o dado novo é incorporado, a tentativa pendente desiste e o agente confirma de novo.
3. **Texto do vendedor sem guardrail**: saía com R$ digitado à mão e ficava cru no outbox junto com o id do canal. Agora passa pelo mesmo guardrail do bot (sem PII do lead, sem R$ fora das cotações da API; o vendedor pode dizer o próprio nome) e o outbox guarda só o `conversation_ref`.
4. **VAULT_KEY trocada** travava toda conversa com CEP (InvalidToken em cada mensagem). Agora a chave aceita rotação (`nova,antiga`), CEP ilegível é tratado como ausente e o agente pede o CEP de novo em vez de cotar sem ele.
5. **Retries pendentes perdidos**: o mapa de pendentes era lido, alterado e gravado inteiro, sem lock global; 10 agendamentos concorrentes deixavam 1. Agora é um hash com um campo por conversa (gravação atômica), removido só depois da tentativa; com várias réplicas, só uma executa cada tentativa.
6. **Operador não conseguia agir com o id da fila** (`conv_...`), só com o id cru, que põe o telefone na URL e no access log. Operador, trace, histórico e outbox aceitam o `conversation_ref`.
7. **Métricas de handoff enganosas**: handoff que chegava por mensagem ativa ficava sem motivo; a espera de 30 s era menor que o ciclo de tentativas (85 s) e deixava conversas sem desfecho fora da conta; `cotacao_indisponivel` contava como coerente para qualquer caso. O outbox passou a trazer estágio e motivo, a espera cobre o ciclo inteiro e a indisponibilidade é contada à parte.
8. Chave com acento no header dava 500 em vez de 401 (`compare_digest` com str não ASCII). Comparação em bytes.
9. Reação (só emoji) e eventos que não são `message.received` do Omni viravam "mídia" e, na segunda, handoff. Agora são ignorados.

Pontos que o revisor verificou e estavam certos: sem deadlock no lock por conversa, interrupt/resume corretos, fila, trace, histórico e logs mascarados, `/omni/webhook` fechado sem chave, mensagens ativas passando pelo guardrail de R$.

## Sessão 1, continuação (29/09/2026): documentação e V1
- README reorganizado em ficha técnica, guia rápido (um comando por bloco), arquitetura com 5 figuras (`docs/figuras/`), operação e referência.
- Conversa exportada para `ai-logs/sessions/` com `scripts/exportar_conversa.py` (só o que aparece na tela) e sanitizador reforçado (headers, Bearer, chaves Fernet, `--valores-de .env`). Histórico do git varrido: nenhuma chave em nenhuma revisão.
- V1 publicada em `FelipeRamosOliveira/namastex-fde-challenge-response`.
- Pedido de Felipe: avisar quando a chave do LLM falta. O agente agora registra um aviso ao subir e `GET /health` mostra `"llm": {"ativo": ..., "provedores": [...], "aviso": ...}`; o README explica onde gerar a chave do Groq e que o avaliador recebe uma chave de 30 dias junto com o link.

## Sessão 2 (30/09/2026): teste de deploy por terceiro e texto livre com LLM
Deploy feito do zero só com o README, no Windows (Docker Desktop, Git Bash, uv 0.10.7), como faria um avaliador externo. Subiu e cotou, mas com atritos, e o teste com Groq mostrou que o LLM quase não mudava as respostas.
- **Respostas iguais às do modo sem LLM**: a frase do redator só era pedida quando o lead fazia pergunta ou não mandava dado nenhum. Em texto livre quase toda mensagem tem algum dado, então a frase não saía (1 chamada em 6 turnos, e essa foi descartada porque repetia "32 anos"). Agora a frase sai sempre que o lead vai além da resposta direta à pergunta; respostas curtas ("sim", "completo", "hoje") seguem sem frase. Na primeira mensagem, a frase vem depois da saudação. Frases com nome de modelo ("HB20") deixaram de ser descartadas; número solto e R$ continuam proibidos.
- **Mesma pergunta 5 vezes**: dados fora de ordem (CEP, plano, data) eram guardados em silêncio e o lead ouvia de novo "Qual é o modelo e o ano do seu carro?". Agora o agente diz o que anotou ("Anotei o CEP.") e, na pergunta repetida, diz o que falta ("Ainda preciso do ano do carro.").
- **"trinta e dois"** era descartado: o LLM entendia, mas a validação exigia os dígitos no texto. Números por extenso (10 a 100) passam a contar; idade inventada continua descartada.
- **"segunda que vem" numa quarta virava sexta** (o prompt só tinha a data, sem o dia da semana). O prompt leva o dia da semana e as regras entendem dias da semana (regra vence o LLM).
- "é do ano passado" e "zero km" viram ano do carro; "comprei ano passado" não (é data da compra).
- Recusa: o lead recebia o texto cru da API ("limite de aceitacao"); agora recebe a razão e o limite em português.
- Deploy: `.python-version` passou de `3.14.7` para `3.14` (uv mais antigo não conhecia o 3.14.7 e `uv run` falhava; o uv não escolhe rc); `.gitattributes` com LF no `.env.example`; README com Python como pré-requisito do passo 2, aviso de Windows (Git Bash/WSL, `python` em vez de `python3`) e dois problemas comuns novos.
- Fluxo mais próximo de uma conversa real (pedido de Felipe): quando o redator escreve a frase, ela substitui o "Anotei ..." em vez de somar (antes eram três confirmações seguidas); a pergunta repetida virou uma frase só ("Pra fazer a cotação, ainda preciso saber o ano do carro (ex.: 2021)."); se o lead já disse o modelo, o agente pergunta só o ano; frase que anuncia passo que o fluxo não dá ("vamos cotar!") ou promete algo é descartada.
- Avaliação com Groq (lead simulado por LLM, 20 casos aleatórios da Gold, `--aleatorio 7`): na primeira tentativa, sem pausa entre mensagens, o Groq recusou 16 de 23 chamadas (429, limite gratuito de 8 mil tokens por minuto dividido com o lead simulado) e o agente caiu nas regras; a rodada foi parada. Medido: extração ~850 tokens, frase ~400. Duas mudanças: `--pausa` no avaliador (tempo de uma pessoa digitar) e o agente deixou de chamar o LLM quando a resposta é curta e as regras já entenderam o dado pedido ("sim", "tenho 35 anos", "completo").
- Primeira rodada com pausa (20 s): 0 recusas do Groq, preço 16/16, PII 0, mas três achados. (1) Bug do agente: o lead mandou a data "01/10/2024", o agente a descartava em silêncio e repetia a pergunta, depois a confirmação, até o limite de turnos; agora diz que a data já passou e pergunta de novo. (2) Só 7 de 20 frases do redator foram usadas: reenviadas as mensagens reais, 12 de 25 caíam só por repetir o ano do carro que o lead escreveu ("seu Toro 2023"); o ano ecoado sai da frase (ano inventado continua derrubando a frase). Frases que prometiam "encaminhar para um especialista" ou "ajustar ao seu orçamento" passavam no filtro e agora são descartadas. (3) Simulador: o lead respondeu `sim` e `FIM` na mesma mensagem e o `sim` contou como fechamento; `FIM` no fim da mensagem agora encerra.
- Segunda rodada, mesma amostra, depois das correções: preço 14/14, PII 0, frases aproveitadas 12/14 (antes 7/20), 25 de 57 extrações sem chamar o LLM. A cota diária do Groq (200 mil tokens, que não aparece no header de limite por minuto) acabou no meio: 3 conversas perdidas por erro do lead e 4 chamadas do agente recusadas (caíram nas regras, como previsto). As duas falhas que restaram são do lead simulado. A remoção do ano deixava "seu HB20 de."; agora leva a preposição junto (coberto por teste; sem cota para nova rodada ao vivo). Resultado em `docs/avaliacao.md` e `docs/avaliacao-groq.json`.
- O fast-agent grava sessões e log em `.fast-agent/` na raiz, com o CEP da persona sem máscara; a pasta não estava no `.gitignore` e um `git add .` depois de avaliar levaria esse dado ao repositório. Adicionada.
- A avaliação também achou: "Não, prefiro ver outro" (outro plano) virou `concorrente` no LLM e foi direto para humano. Regra nova de `pergunta_planos` para "ver outro"/"outro plano", que vence o `concorrente` do LLM quando a regra não viu concorrente.

## Sessão 3 (30/09/2026): auditoria independente da V1
Dois agentes auditores separados, sem terem escrito o código, revisaram a V1 como faria um avaliador: um a documentação e outro o código. Os achados mais graves foram conferidos no código antes de entrar aqui.
- **Checagens:** 211 testes passando no Python 3.14.7, ruff limpo, sanitizador dos ai-logs sem achados, números de `docs/avaliacao.md` iguais aos dos JSONs.
- **Código:** achados de durabilidade do fluxo assíncrono (tentativas pendentes dependem do Redis sem persistência, entrega ativa sem reentrega, deduplicação só em memória, falha no registro do handoff), formatos de PII fora dos padrões, filtro da frase do LLM sem numerais por extenso, hashes sem chave, `quote_id` compartilhado pelo cache e carga extra do hedging. Decisão: não alterar o código perto da entrega; tudo documentado com próximo passo no README 5.7 e nos ADRs.
- **Documentação corrigida:** afirmação absoluta sobre PII no README trocada pela descrição real; `pii_detectada` vazio no rastreio explicado; cenário `resiliencia` passou a dizer que a falha é injetada no cliente e que os intervalos foram encurtados; comandos de reprodução da avaliação completos (`--url` obrigatório, `--extra sim`, estresse, `--saida`); 17 de 20 conversas na rodada com Groq; `TRACE_API_KEY` descrita como necessária para vendedor e rastreio; erro do Python 3.14.0rc2 na tabela de problemas comuns; ADRs com contexto, alternativas e consequências negativas; PLANO marcado como histórico; um trecho de chave removido do log da parte 2.
- **Rejeitado:** a sugestão de tirar dos ai-logs a análise da solução do outro candidato. Ela fica, porque faz parte do processo real (seção acima).

## Sessão 4 (30/09/2026): correção dos achados da auditoria
Felipe reviu a decisão da sessão 3 (só documentar) e pediu para corrigir o máximo dos nove achados sem mexer no que já funcionava. Todos os nove foram tratados (ADR 0009), cada um com teste em `tests/integration/test_auditoria.py` ou nos testes unitários; os testes novos não rodam sem as correções.
- Segundo plano: `retry_em` no checkpoint, reconciliação na subida e na mensagem do lead, AOF no Redis.
- Entrega ativa: fila de reentrega com backoff e eventos `entrega_falhou`/`entrega_reentregue`/`entrega_desistiu`.
- Idempotência: resposta por `message_id` no Redis (48 h), sem o id do canal.
- Handoff: `handoff_id` gerado no grafo, registro idempotente com 3 tentativas e conclusão em segundo plano; status na fila e filtro `?status=`.
- PII: CEP com espaço/ponto, CNPJ, RG, cartão (Luhn), sobrenome depois de "da"/"de". Um teste antigo pegou uma regressão no meio do caminho (CEP seguido de vírgula deixou de casar) e a lista de palavras que não são nome ganhou "dos"/"das" (sem isso, todo "dos" da mensagem seria mascarado).
- Pseudônimos: HMAC com `PSEUDONIMO_KEY`, opcional para não mudar os ids de quem já está no ar.
- Frase do LLM: filtro de valor por extenso e condição genérica; frases fixas por índice rejeitadas (ver ADR).
- Cache: `quote_id` por entrega com `source_quote_id`. O teste antigo afirmava o comportamento que a auditoria apontou como defeito (mesmo `quote_id`) e foi atualizado.
- Hedge com orçamento e desligado com o circuito degradado.
- Rejeitado por ora: detectar nome sem frase de apresentação (falso positivo demais sem NER).
