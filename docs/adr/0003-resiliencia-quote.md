# ADR 0003: Resiliência na chamada à /quote

- Status: aceito (29/09/2026)

## Contexto
A `/quote` falha 20% das vezes (500, 502, 503) e 10% das vezes demora 8 s. O brief diz que é o ponto que mais separa candidatos. A solução concorrente usa timeout de 12 s com 3 tentativas síncronas (pior caso de cerca de 37 s).

## Decisão
1. Timeout total de 2,5 s por tentativa (`asyncio.timeout`; o timeout do httpx é por operação).
2. Hedging: se a tentativa passa de 1,2 s, dispara outra em paralelo e usa a primeira resposta. Seguro porque `/quote` só calcula.
3. Retry com backoff exponencial e jitter só para 5xx, timeout e transporte; até 4 chamadas.
4. 422 e 400 não repetem.
5. Circuit breaker no Redis: conta cotações falhas (não tentativas, para o hedging não inflar a conta); 3 seguidas abrem por 15 s. Na meia-abertura passa uma única sonda (trava `SET NX`), com uma tentativa só.
6. Resposta 200 com corpo inválido (sem `premio_mensal`, `franquia`, `plano_nome`, `coberturas`) é falha transitória e nunca vai para o cache.
7. Cache da resposta real por payload normalizado + dia, até meia-noite (a regra de idade do veículo depende do ano corrente).

## Evidência (testes)
- API 100% lenta: falha em menos de 8 s, sem preço.
- Instabilidade padrão, 30 cotações: pelo menos 29 com sucesso e p95 abaixo de 3 s.
- Hedging: chamada de 5 s vencida pela segunda em cerca de 0,2 s.

## Alternativas consideradas
- **Timeout longo e síncrono** (o da solução concorrente: 12 s com 3 tentativas): simples, mas o lead espera até cerca de 37 s e a chamada lenta de 8 s sempre é aguardada.
- **Handoff direto na primeira falha:** manda ao vendedor um problema que se resolve em segundos. Substituído pela cotação em segundo plano (ADR 0008).

## Consequências
- O pior caso de espera do lead num turno fica em poucos segundos (máximo de 6,2 s medido na avaliação), e a chamada lenta nunca é esperada inteira.
- Custo: o hedging manda uma segunda chamada quando a primeira passa de 1,2 s, o que aumenta a carga justamente quando a API está lenta. O breaker só abre depois de 3 cotações falhas. Próximo passo em README 5.7.
- O cache reaproveita o `quote_id` da resposta original para leads com o mesmo perfil no mesmo dia (README 5.7).

## Complemento
A resposta imediata ao lead e a nova tentativa em segundo plano estão no ADR 0008.
