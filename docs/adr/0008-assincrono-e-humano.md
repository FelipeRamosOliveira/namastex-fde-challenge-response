# ADR 0008: Cotação em segundo plano e humano no circuito com LangGraph

- Status: aceito (29/09/2026)

## Contexto
Na etapa 3, uma /quote fora do ar levava direto ao humano. A instabilidade do desafio é transitória: mandar para o vendedor algo que se resolve em segundos é desperdício. E o handoff só registrava na fila: o vendedor não tinha como responder nem devolver a conversa ao bot.

## Decisão
**Cotação em segundo plano**
- Se a /quote falha depois das tentativas rápidas (ADR 0003), o nó `cotar` responde uma vez que está tentando de novo, muda o estado para `aguardando_cotacao` e pede nova tentativa em N segundos (`RETRY_FUNDO_DELAYS_S`, padrão 5, 20 e 60 s).
- A fachada agenda a tentativa e reexecuta o grafo com um evento de sistema no mesmo `thread_id`: o grafo continua do checkpoint, com todos os dados da conversa.
- Deu certo: o lead recebe "Consegui!" e a cotação pelo `Outbox` (webhook do canal ou `GET .../outbox`). Esgotou: handoff `cotacao_indisponivel`.
- Mensagens do lead enquanto espera recebem "ainda estou tentando"; pedido de humano continua valendo.
- Tentativas pendentes ficam no KVStore e são reagendadas se o processo reiniciar.

**Humano no circuito**
- Depois do handoff, o nó `aguardar_humano` chama `interrupt()`: a conversa fica pausada no checkpoint.
- Mensagens do lead durante a pausa entram no histórico com `aupdate_state(as_node="saida")`, sem acordar o grafo (testado: o próximo passo continua `aguardar_humano`).
- O operador (`POST .../operador`) pode responder o lead, devolver a conversa ao bot (`Command(resume={"acao": "devolver"})`, o bot retoma pelo dado que falta) ou encerrar.
- O registro na fila acontece no nó `handoff`, antes do `interrupt`, para não duplicar na retomada.

**Concorrência**
- Lock por conversa no KVStore: `asyncio.Lock` num processo, lock do Redis entre réplicas.

**Rastreio**
- `GET .../historico` usa `aget_state_history`: cada checkpoint, o nó que rodou e o próximo passo.

## Consequências
- Menos handoffs desnecessários: uma queda de 30 s não chega ao vendedor.
- O canal precisa entregar mensagens ativas (webhook ou polling); o Omni faz isso na etapa 6.
- Limitações (README 5.7): as tentativas pendentes dependem do Redis, que no compose roda sem persistência; a entrega ativa não tem reentrega se falhar; a deduplicação por `message_id` fica na memória do processo; se o registro na fila falhar, a conversa pausa sem item na fila.
