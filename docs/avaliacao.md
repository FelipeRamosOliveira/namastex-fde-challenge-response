# Avaliação (etapa 8)

Leads simulados a partir da Gold (conversas reais do dataset, mascaradas) conversando com o agente em processo, contra a **quote-api original** do desafio. O lead é o `LeadRoteiro` (determinístico): responde o que o bot pergunta e segue o desfecho original da conversa (ganho fecha, perdido e em negociação objetam, sem resposta some). O preço esperado vem da resposta da API gravada na Gold.

Reproduzir (quote-api no ar):
```bash
uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 300
```

## Resultado: instabilidade padrão do desafio (20% falha, 10% lenta)
300 conversas, 16 em paralelo, 38 s no total. Detalhe por conversa em `docs/avaliacao.json`.

| Métrica | Resultado |
|---|---|
| Elegíveis que chegaram à cotação | **210/210** |
| Preço mostrado igual ao da API | **284/284** |
| Handoff com motivo coerente com o caso | **258/258** (61 pronto para fechar, 107 objeção, 90 recusa por regra) |
| Cotações entregues em segundo plano (API falhou na hora) | 5 |
| Respostas do agente com PII | **0** |
| Latência por turno | p50 236 ms, p95 334 ms, máx 6,3 s |

## Resultado: estresse (50% falha, 20% lenta)
100 conversas. `docs/avaliacao-estresse.json`.

| Métrica | Resultado |
|---|---|
| Elegíveis que chegaram à cotação | **72/72** |
| Preço mostrado igual ao da API | **96/96** |
| Handoff coerente | **87/87** |
| Cotações entregues em segundo plano | **29** |
| Respostas com PII | **0** |
| Latência por turno | p50 52 ms, p95 1,2 s, máx 5,2 s |

Com metade das chamadas falhando, nenhuma conversa foi para o humano por causa da API: as falhas foram absorvidas pelo retry rápido (hedging) e, quando não bastou, pela nova tentativa em segundo plano.

## Limites desta avaliação
- O `LeadRoteiro` é objetivo; a variedade de linguagem é coberta pelos testes de extração (Gold com mensagens reais) e pelo `LeadFastAgent` (LLM), que roda com `--lead fastagent` e precisa do Groq.
- O máximo de 6,3 s é o turno em que as tentativas rápidas falharam antes de o agente avisar o lead e passar para o segundo plano.
- LLM desligado nesta rodada (reprodutível e sem cota); com o Groq, a extração é LLM validado + regras (ADR 0007).
