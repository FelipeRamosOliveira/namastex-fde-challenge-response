# Avaliação (etapa 8)

Leads simulados a partir da Gold (conversas reais do dataset, mascaradas) conversando com o agente no ar (`agent-api` do Docker), pela mesma API que o canal usa, contra a **quote-api original** do desafio. O lead é o `LeadRoteiro` (determinístico): responde o que o bot pergunta e segue o desfecho original da conversa (ganho fecha, perdido e em negociação objetam, sem resposta some). O preço esperado vem da resposta da API gravada na Gold.

### Reproduzir
Pré-requisitos: os 4 containers no ar (guia rápido do README) e as chaves carregadas no terminal (`set -a; . ./.env; set +a`), porque o avaliador envia `CHANNEL_API_KEY` no header. O `--url` é obrigatório. Use `--saida` para não sobrescrever os resultados versionados.

```bash
# 1. Instabilidade padrão (20% falha, 10% lenta), 300 conversas
uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 300 --saida /tmp/avaliacao.json

# 2. Estresse (50% falha, 20% lenta), 100 conversas: sobe a quote-api com outra taxa e roda
QUOTE_FAILURE_RATE=0.5 QUOTE_SLOW_RATE=0.2 docker compose up -d quote-api
uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 100 --saida /tmp/avaliacao-estresse.json
docker compose up -d quote-api   # volta à instabilidade padrão

# 3. Com LLM nos dois lados: precisa do extra do simulador e de GROQ_API_KEY
uv sync --extra sim
uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 20 --aleatorio 7 --lead fastagent --concorrencia 1 --pausa 20 --saida /tmp/avaliacao-groq.json
```

## Resultado: instabilidade padrão do desafio (20% falha, 10% lenta)
300 conversas, 8 em paralelo. Detalhe por conversa em `docs/avaliacao.json`.

| Métrica | Resultado |
|---|---|
| Elegíveis que chegaram à cotação | **210/210** |
| Preço mostrado igual ao da API | **284/284** |
| Handoff com motivo coerente com o caso | **258/258** (61 pronto para fechar, 107 objeção, 90 recusa por regra) |
| Handoff por API indisponível (contado à parte) | 0 |
| Conversas sem desfecho | 0 |
| Cotações entregues em segundo plano (API falhou na hora) | 4 |
| Respostas do agente com PII | **0** |
| Latência por turno | p50 90 ms, p95 167 ms, máx 6,2 s |

## Resultado: estresse (50% falha, 20% lenta)
100 conversas. `docs/avaliacao-estresse.json`.

| Métrica | Resultado |
|---|---|
| Elegíveis que chegaram à cotação | **72/72** |
| Preço mostrado igual ao da API | **96/96** |
| Handoff coerente | **87/87** |
| Handoff por API indisponível | 0 |
| Conversas sem desfecho | 0 |
| Cotações entregues em segundo plano | **18** |
| Respostas com PII | **0** |
| Latência por turno | p50 27 ms, p95 1,2 s, máx 3,9 s |

Com metade das chamadas falhando, nenhuma conversa foi para o humano por causa da API: as falhas foram absorvidas pelo retry rápido (hedging) e, quando não bastou, pela nova tentativa em segundo plano.

## Resultado: com LLM (Groq) nos dois lados
20 casos aleatórios da Gold (`--aleatorio 7`), lead interpretado por LLM (fast-agent + Groq, conversa livre) e agente com Groq ligado, uma conversa por vez, 20 s entre mensagens (tempo de uma pessoa digitar). 17 dos 20 casos foram concluídos: os outros 3 caíram porque a cota diária do Groq acabou no meio da rodada. `docs/avaliacao-groq.json` (comando no item 3 de "Reproduzir").

As linhas "Guardrail de saída acionado", "Extrações que dispensaram o LLM" e "Frases do redator aproveitadas" não estão no JSON, que guarda só as métricas do simulador; a contagem está descrita no `DEVLOG.md` (sessão 2).

| Métrica | Resultado |
|---|---|
| Elegíveis que chegaram à cotação | 10/11 (a que faltou: a persona "some" sumiu antes de confirmar) |
| Preço mostrado igual ao da API | **14/14** |
| Handoff coerente | 13/14 (o que faltou: persona "some" que aceitou a cotação) |
| Respostas com PII | **0** |
| Guardrail de saída acionado | 0 |
| Extrações que dispensaram o LLM (resposta curta já entendida pelas regras) | 25/57 |
| Frases do redator aproveitadas | 12/14 (na rodada anterior às correções: 7/20) |
| Latência por turno | p50 432 ms, p95 1,2 s, máx 1,4 s |
| Conversas perdidas por erro do lead simulado | 3 (acabou a cota diária do Groq no meio da rodada) |

Consumo medido do agente: extração ~850 tokens, frase ~400; em média ~1,9 mil tokens por conversa. O plano gratuito do Groq tem 8 mil tokens por minuto e 200 mil por dia: dá para ~100 conversas por dia só com o agente. O lead simulado gasta a mesma cota e bem mais por conversa, por isso a avaliação usa pausa e fica em 20 casos.

As duas falhas restantes são do lead simulado, que nem sempre segue a persona; o agente respondeu certo nos dois casos. A primeira rodada (antes das correções da sessão 2) achou os problemas descritos no `DEVLOG.md`.

## Limites desta avaliação
- O `LeadRoteiro` é objetivo; a variedade de linguagem é coberta pelos testes de extração (Gold com mensagens reais) e pelo `LeadFastAgent` (LLM), que roda com `--lead fastagent` e precisa do Groq.
- Métricas corrigidas na segunda revisão: o motivo do handoff que chega por mensagem ativa vem do próprio item do outbox, a espera cobre o ciclo inteiro de tentativas (5 + 20 + 60 s) e handoff por API indisponível não conta como coerente. Antes, a espera de 30 s podia deixar conversas sem desfecho fora da conta.
- O máximo de 6,2 s é o turno em que as tentativas rápidas falharam antes de o agente avisar o lead e passar para o segundo plano.
- LLM desligado nas rodadas de 300 e 100 conversas (reprodutível e sem cota); com o Groq, a extração é LLM validado + regras (ADR 0007). A rodada com Groq tem só 20 casos por causa da cota gratuita e não é reprodutível (o LLM varia).
