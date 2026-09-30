# Plano de solução: Agente AutoSeguro (desafio FDE Namastex)

> **Documento histórico.** Este é o plano inicial, escrito antes do código, mantido para mostrar o processo. O que foi implementado está no README e nos ADRs. Divergências conhecidas: os nós do grafo são `entrada`, `decidir`, `cotar`, `handoff`, `saida` e `aguardar_humano`; o hedging dispara em 1,2 s; o Omni real e o canal Harness ficaram fora do compose (`docs/omni.md`); as execuções completas estão em `docs/execucao/`; a meta de acerto de extração não foi medida à parte (a avaliação mede o resultado de ponta a ponta).

Versão 1, 29/09/2026. Plano em etapas; cada etapa termina com testes que dizem se ela está pronta.

## 0. Regras de ouro (valem para todas as etapas)

| Regra | Como garantir | Teste que prova |
|---|---|---|
| **PII protegida** | Guardrail na entrada mascara CPF, e-mail, telefone, placa e nome antes de qualquer LLM, log ou trace. Guardrail na saída bloqueia PII na resposta | Scanner roda nas 26.470 mensagens do dataset e acha **0 vazamentos** após a máscara; teste com espião confirma que o LLM só recebe texto mascarado |
| **Valores reais** | O LLM **nunca escreve dinheiro**. Preço, franquia, carência e pro-rata saem por template a partir da resposta da `/quote`. Validador de saída bloqueia qualquer número em R$ que não esteja na resposta da API | Teste com resposta da API aleatória: 100% dos valores mostrados batem com o JSON da API; resposta do LLM com preço inventado é bloqueada |
| **Omni na solução** | Agente exposto como *provider* webhook do Omni; simulação pelo canal **Harness** do Omni (canal de teste E2E que captura as mensagens) | Conversa completa passando pelo Omni no Docker (etapa 6) |

## 1. Stack confirmada (testada hoje)

Instalei e importei as bibliotecas em **Python 3.14.7**:

| Peça | Versão | Status |
|---|---|---|
| Python | 3.14.7 | OK (cuidado: o 3.14.0rc2 quebra com pydantic; fixar 3.14.7 ou mais novo) |
| LangGraph | 1.2.12 | OK |
| FastMCP | 4.0.5 | OK |
| fast-agent-mcp | 0.10.39 | OK (tem provedores Groq, OpenRouter e "generic") |
| langgraph-checkpoint-sqlite | atual | OK |
| langchain-mcp-adapters | 0.3.1 | **Quebra** com mcp 2.x. Solução: chamar as tools pelo `fastmcp.Client` direto dentro dos nós do LangGraph |

**LLM gratuito (proposta):** Groq como principal (30 req/min, 1.000 req/dia, tool calling, não usa dados para treino) e OpenRouter free como reserva. Os dois são compatíveis com a API da OpenAI. Mesmo assim, só texto mascarado sai da máquina.

**Omni hoje:** o repositório ativo é `automagik-dev/omni` (TypeScript/Bun, PostgreSQL, NATS). Aceita agente externo via provider `webhook` e tem o canal **Harness** para testes sem WhatsApp real. Não tem Docker oficial documentado: é o maior risco do plano (ver etapa 6).

## 2. Papel de cada biblioteca

LangGraph e fast-agent fazem coisas parecidas. Para não ter dois orquestradores, a divisão proposta é:

| Biblioteca | Papel |
|---|---|
| **LangGraph** | Cérebro do atendimento: máquina de estados da conversa, com estado persistido por `conversation_id` |
| **FastMCP** | Servidor MCP `autoseguro-tools` com as ferramentas: `consultar_planos`, `pre_validar`, `cotar`, `registrar_handoff` |
| **fast-agent** | **Simulador de lead e avaliação**: agentes com persona tirada do dataset conversam com o nosso agente de ponta a ponta. Também serve para testar o servidor MCP no terminal |
| **FastAPI** | Porta de entrada assíncrona: webhook do Omni, API de simulação e endpoint de trace |

A cotação é chamada **por um nó determinístico**, não por escolha do LLM. O LLM só extrai dados e escreve a parte conversacional.

## 3. Arquitetura alvo (resumo)

```
Lead -> Omni (Harness ou WhatsApp) -> webhook FastAPI
     -> [Guardrail PII entrada] -> LangGraph:
          extrair (LLM) -> validar (regras /planos) -> perguntar faltantes ou confirmar
          -> cotar (MCP: cliente resiliente + cache) -> apresentar (template)
          -> decidir (regras de handoff) -> [Guardrail saída: PII + valores]
     -> resposta ao Omni
Apoio: Redis (cache, circuit breaker), SQLite (checkpoints LangGraph + eventos), fila de handoff
Offline: parquet -> Bronze -> Silver (mascarado) -> Gold (casos de avaliação)
```

## 4. Cache (reduz custo e latência)

| Camada | Chave | Validade | Observação |
|---|---|---|---|
| `/planos` | fixa | 1 hora | Usado só para pré-validar e explicar regras, nunca para calcular preço |
| **Cotação** | hash do payload normalizado + data de hoje | até o fim do dia | Guarda a **resposta real** da API com `quote_id` e horário; a regra "valores reais" continua valendo. Evita chamar uma API instável duas vezes para a mesma pergunta |
| LLM (extração) | hash do texto mascarado + modelo + versão do prompt | 7 dias | Cache exato; útil nas avaliações que repetem mensagens |

## 5. Critérios de handoff (explícitos)

| Motivo | Quando | O que o humano recebe |
|---|---|---|
| `recusa_regra` | Pré-validação ou 422 (idade acima de 75, carro com mais de 20 anos) | Motivo da regra e dados mascarados |
| `cotacao_indisponivel` | `/quote` segue falhando depois da janela de nova tentativa em segundo plano (ex.: 2 min) | Tentativas, erros e dados prontos para cotar |
| `pedido_humano` | Lead pede atendente | Resumo da conversa |
| `objecao_preco` | Segunda objeção de preço ou menção a concorrente | Cotação feita e objeção |
| `fora_de_escopo` | Sinistro, cancelamento, outro produto | Resumo |
| `midia` | Áudio, imagem ou documento depois de um pedido para escrever | Tipo de mídia |
| `sem_progresso` | N turnos sem novo dado | Dados já coletados |
| **`pronto_para_fechar`** | Lead aceita a proposta ("fechado", "pode emitir") | Lead quente com cotação: emissão de apólice e boleto é trabalho humano, igual ao dataset |

## 6. Etapas testáveis

### Etapa 0. Fundação do repo e memória de desenvolvimento (dia 1, manhã)
**Faz:**
- Repo novo (ex.: `autoseguro-agent`), com o repo do desafio como **submódulo git** em `vendor/challenge`. Assim a API e o dataset são os originais, sem cópia editada.
- `pyproject.toml` com uv e Python 3.14.7, ruff, pytest e pytest-asyncio.
- `docker-compose.yml` com `quote-api` (do submódulo) e `redis`.
- **Memória do desenvolvimento assistido por IA:**
  - `CLAUDE.md`: contexto, regras de ouro e convenções (usar a skill `scaffold-projeto-ia`);
  - `docs/adr/`: uma decisão por arquivo (ADR);
  - `docs/DEVLOG.md`: por sessão, o que a IA sugeriu, o que foi aceito ou rejeitado e por quê;
  - `ai-logs/`: export bruto das sessões, passando por um script que remove segredos e PII antes do commit;
  - hooks de pre-commit com gitleaks e o scanner de PII.
- Commits pequenos e frequentes, para mostrar o processo.

**Pronto quando:** `docker compose up` sobe a API e `GET /health` responde; CI roda lint e testes vazios; um commit com segredo falso é barrado pelo hook.

### Etapa 1. Dados: Bronze, Silver e Gold (dia 1, manhã)
**Faz:**
- **Bronze:** leitura do parquet sem alteração.
- **Silver:** ordena por `message_index`, mascara PII com tokens (`[CPF_1]`), normaliza `veiculo_texto` para marca, modelo e ano, e marca as mensagens de mídia.
- **Gold:** casos de avaliação: roteiro de mensagens do lead e resultado esperado (cotar, recusar ou handoff). O preço esperado vem da **API real** rodando com `QUOTE_FAILURE_RATE=0`, e não de conta própria.
- Taxonomia de objeções tirada do dataset.

**Pronto quando:**
- scanner de PII nas mensagens da Silver: **0 ocorrências**;
- testes de regex cobrem os formatos do dataset e as variações (telefone sem +55, placa antiga e Mercosul, CPF com e sem pontos);
- existem pelo menos 200 casos Gold, incluindo recusas por idade e por idade do carro.

### Etapa 2. Ferramentas MCP e cliente resiliente (dia 1, tarde)
**Faz:**
- Servidor FastMCP com 4 ferramentas.
- Cliente assíncrono (`httpx.AsyncClient` com pool) com:
  - timeout curto (~2,5 s);
  - **hedging**: se a primeira chamada passar de ~1,5 s, dispara uma segunda e fica com a que responder primeiro. É seguro porque a cotação só lê e calcula;
  - retry com backoff e jitter só para 5xx e timeout;
  - sem retry para 422 e 400;
  - circuit breaker guardado no Redis;
  - cache de cotação.
- Pré-validação com as regras de `/planos`.

**Pronto quando** (testes com `QUOTE_SEED` fixo):
- `FAILURE_RATE=1` devolve `indisponivel` sem nenhum preço;
- `SLOW_RATE=1` responde em menos de 3 s graças ao hedging, ou falha rápido;
- 422 faz uma única tentativa;
- o circuit breaker abre depois de N falhas e fecha depois do tempo de espera;
- a segunda cotação igual no mesmo dia vem do cache com o mesmo `quote_id`;
- o pro-rata e a carência aparecem quando há `data_inicio`.

### Etapa 3. Grafo LangGraph sem LLM (dia 2, manhã)
**Faz:**
- Grafo com os nós: `guardrail_entrada`, `extrair`, `validar`, `perguntar`, `confirmar`, `cotar`, `apresentar`, `decidir` e `guardrail_saida`.
- A extração ainda é um stub determinístico.
- Checkpointer SQLite assíncrono, com `thread_id = conversation_id`.
- Antes de cotar, **confirma os dados com o lead**.

**Pronto quando:** existem testes de grafo para caminho feliz, dado faltando, recusa, correção de dado pelo lead e retomada da conversa depois de reiniciar o serviço.

### Etapa 4. LLM gratuito e guardrails (dia 2, manhã)
**Faz:**
- Extração com saída estruturada (schema Pydantic) via Groq, com OpenRouter como reserva.
- Poucos exemplos (few-shot) tirados da Silver.
- Cache de LLM.
- Guardrail de saída de valores: resposta = template com os números + texto do LLM sem números.

**Pronto quando:**
- espião mostra **0 PII** nos prompts;
- um LLM falso que inventa "R$ 99,90" tem a resposta bloqueada;
- acerto de extração acima de 95% nos casos Gold;
- os casos que enganaram o concorrente passam: "começar em 2026-10-15" **não vira ano do carro** e "carro tem 12 anos" **não vira idade**;
- sem chave de LLM, o agente segue funcionando com extração por regras.

### Etapa 5. Assíncrono e handoff (dia 2, tarde)
**Faz:**
- Se a cotação demora, o agente responde "estou consultando, já te retorno" e continua em segundo plano.
- Se falha, tenta de novo em segundo plano dentro da janela; só depois disso faz o handoff.
- Fila de handoff (Redis Streams ou tabela) com resumo estruturado e mascarado para o vendedor.
- As 8 regras de handoff ficam em código, com uma tabela no README.

**Pronto quando:** há um teste para cada motivo de handoff; com a API fora por 30 s e depois de volta, **o lead recebe a cotação sem ir para o humano**; p95 da primeira resposta abaixo de 2 s com as falhas padrão.

### Etapa 6. Canal: Omni e simulador (dia 3, manhã)
**Faz:**
- Endpoint `POST /omni/webhook` no contrato do provider webhook do Omni.
- Perfil `omni` no Docker Compose: Omni, PostgreSQL e NATS, com o canal Harness.
- **Spike com prazo de 4 horas.** Se o Omni não subir limpo no Docker, o plano B é um adaptador que segue o mesmo contrato e um simulador próprio; o README explica e mostra o comando para plugar no Omni real.
- Simulador de leads com fast-agent (personas da Gold) falando pela API.

**Pronto quando:** uma conversa completa atravessa o Omni (ou o adaptador) com cotação real no fim; o simulador roda 50 conversas sem erro.

### Etapa 7. Rastreio e log de execução (dia 3, manhã)
**Faz:**
- Tabela de eventos com `conversation_id`, `message_id`, `quote_request_id`, `attempt`, `status`, latência e motivo do handoff.
- `GET /conversations/{id}/trace` protegido por chave, devolvendo **só dados mascarados**.
- Script que exporta o log de uma execução completa para `docs/execucao-completa.jsonl` e para uma versão legível em `.md`.

**Pronto quando:** dá para responder "por que o lead X foi para o humano?" só com o trace; o log exportado passa pelo scanner de PII com 0 ocorrências.

### Etapa 8. Avaliação e entrega (dia 3, tarde)
**Faz:**
- Roda a avaliação na Gold com falhas ligadas.
- **Métricas:** conversas resolvidas, acerto dos handoffs, **acerto de preço (meta 100%)**, **vazamento de PII (meta 0)**, latência p50 e p95, chamadas de LLM economizadas pelo cache.
- README com como rodar, decisões (link para os ADRs), tabela de handoff e resultados.
- Export final dos `ai-logs/`.
- Revisão final por um agente separado, que não viu o código ser escrito.

**Pronto quando:** `docker compose up` roda do zero numa máquina limpa; todas as metas atingidas ou explicadas no README.

## 7. Riscos e plano B

| Risco | Plano B |
|---|---|
| Omni pesado ou sem Docker | Adaptador com o mesmo contrato + instrução de uso com Omni real |
| Limite diário do LLM gratuito | Cache + troca para OpenRouter + extração por regras |
| Bibliotecas novas no Python 3.14 | Versões fixadas no `uv.lock`; já testado hoje |
| Prazo de 3 dias | Etapas 0 a 5 são o núcleo; 6 a 8 podem ser reduzidas sem quebrar a entrega |

## 8. Decisões para confirmar
1. Papel do fast-agent como **simulador e avaliação** (e não como segundo orquestrador).
2. Groq como LLM principal e OpenRouter free como reserva.
3. Omni via canal Harness no Docker (sem WhatsApp real), com spike de 4 horas.
4. Nome do repo e se fica na sua conta pessoal.
