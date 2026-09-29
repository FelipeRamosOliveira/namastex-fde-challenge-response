# ADR 0003: Resiliência na chamada à /quote

- Status: aceito (29/09/2026)

## Contexto
A `/quote` falha 20% das vezes (500, 502, 503) e 10% das vezes demora 8 s. O brief diz que é o ponto que mais separa candidatos. A solução concorrente usa timeout de 12 s com 3 tentativas síncronas (pior caso de cerca de 37 s).

## Decisão
1. Timeout total de 2,5 s por tentativa (`asyncio.timeout`; o timeout do httpx é por operação).
2. Hedging: se a tentativa passa de 1,2 s, dispara outra em paralelo e usa a primeira resposta. Seguro porque `/quote` só calcula.
3. Retry com backoff exponencial e jitter só para 5xx, timeout e transporte; até 4 chamadas.
4. 422 e 400 não repetem.
5. Circuit breaker no Redis: 5 falhas seguidas abrem por 15 s; depois, meia-abertura.
6. Cache da resposta real por payload normalizado + dia, até meia-noite (a regra de idade do veículo depende do ano corrente).

## Evidência (testes)
- API 100% lenta: falha em menos de 8 s, sem preço.
- Instabilidade padrão, 30 cotações: pelo menos 29 com sucesso e p95 abaixo de 3 s.
- Hedging: chamada de 5 s vencida pela segunda em cerca de 0,2 s.

## Próximo (etapa 5)
Resposta imediata de "estou consultando" e nova tentativa em segundo plano antes do handoff.
