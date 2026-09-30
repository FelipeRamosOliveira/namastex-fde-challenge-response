# ADR 0006: Dataset em camadas Bronze, Silver e Gold

- Status: aceito (29/09/2026)

## Contexto
O dataset tem PII em todas as conversas, timestamps fora de ordem e preço de vendedor aleatório. Era preciso uma base limpa para testar a extração e um gabarito de preço que não fosse recalculado em Python (regra de ouro 2).

## Decisão
- Bronze: parquet original no submódulo, sem alteração.
- Silver: ordenada por `message_index` (os timestamps estão fora de ordem em 2.495 de 2.500 conversas), PII mascarada, veículo normalizado, CEP reduzido ao prefixo, remetentes pseudonimizados.
- Gold: 300 casos estratificados por desfecho e por recusa esperada; roteiro do lead + resposta real da API para os 3 planos.

## Consequências
- O preço citado pelos vendedores no dataset é aleatório e não segue as regras; não serve de gabarito de preço.
- A Gold depende da data em que foi gerada: a idade do veículo e o cache da API usam o ano corrente. Em outro ano, regerar com `uv run python -m autoseguro.data.pipeline gold --quote-url http://localhost:8000`.
