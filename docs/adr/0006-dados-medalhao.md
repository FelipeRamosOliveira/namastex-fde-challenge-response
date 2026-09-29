# ADR 0006: Dataset em camadas Bronze, Silver e Gold

- Status: aceito (29/09/2026)

## Decisão
- Bronze: parquet original no submódulo, sem alteração.
- Silver: ordenada por `message_index` (os timestamps estão fora de ordem em 2.495 de 2.500 conversas), PII mascarada, veículo normalizado, CEP reduzido ao prefixo, remetentes pseudonimizados.
- Gold: 300 casos estratificados por desfecho e por recusa esperada; roteiro do lead + resposta real da API para os 3 planos.

## Observação
O preço citado pelos vendedores no dataset é aleatório e não segue as regras; não serve de gabarito de preço.
