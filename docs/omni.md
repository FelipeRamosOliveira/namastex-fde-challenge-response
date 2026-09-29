# Omni como canal

O agente é um **provider `webhook`** do [Omni](https://github.com/automagik-dev/omni) (Namastex). Contrato lido do código do Omni (`packages/core/src/providers/webhook-provider.ts`, commit `906a420`):

| Direção | Como |
|---|---|
| Omni -> agente | `POST /omni/webhook`, `Authorization: Bearer <OMNI_PROVIDER_KEY>`, corpo `WebhookPayload` (`event`, `instance`, `chat`, `sender`, `content.text`, `traceId`) |
| Resposta | `{"reply": "..."}` (modo round-trip, padrão do Omni) |
| Agente -> Omni (ativa) | `POST {OMNI_URL}/api/v2/messages/send`, `x-api-key: <OMNI_API_KEY>`, `{"instanceId", "to", "text"}`: cotação em segundo plano, resposta do vendedor, devolução ao bot |

Detalhes que o adaptador trata:
- `conversation_id = omni:<instance>:<chat>`, transformado em hash (`conversation_ref`) antes de ir para estado e logs; o nome do remetente (`sender.name`) é descartado.
- O Omni reenvia o webhook uma vez em erro 5xx; o agente é idempotente por `event.id`.
- Mensagem sem texto (mídia, figurinha) vira pedido para escrever.

## Plugar num Omni de verdade
1. Omni no ar (`install.sh --server` ou o chart Helm do repositório do Omni).
2. No `.env` do agente: `OMNI_PROVIDER_KEY` (segredo que o Omni vai mandar), `OMNI_URL` e `OMNI_API_KEY` (para mensagens ativas).
3. Registrar o provider e o agente:
   ```bash
   omni providers create --name autoseguro --schema webhook \
     --base-url http://<host-do-agente>:8080/omni/webhook --api-key <OMNI_PROVIDER_KEY>
   omni agents create --name autoseguro --agent-provider <provider-id>
   ```
4. Canal de teste sem WhatsApp real (Harness): `omni instances create --name teste --channel harness --agent <agent-id>`, depois
   `POST /api/v2/channels/harness/<instance-id>/say {"chatId": "lead-1", "text": "oi"}` e
   `GET /api/v2/channels/harness/<instance-id>/transcript?chatId=lead-1`.
5. WhatsApp real: a mesma coisa com `--channel whatsapp-baileys` (login por QR).

## Status
- Adaptador e contrato: implementados e testados (`tests/integration/test_omni.py`) com um Omni falso que segue o contrato do código-fonte: conversa completa, cotação em segundo plano saindo pelo `messages/send` com `instanceId` e `to` corretos, resposta do vendedor, reentrega idempotente, mídia, autenticação.
- Omni real no `docker compose`: **não incluído**. O Omni oficial roda com Postgres, NATS e MinIO via Helm (arm64 por padrão); não foi possível validar essa subida no ambiente de desenvolvimento (Docker Hub bloqueado). Os passos acima são os do CLI atual do Omni, conferidos no código dele.
