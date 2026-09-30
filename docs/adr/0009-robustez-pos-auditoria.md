# ADR 0009: Robustez depois da auditoria pós-V1

- Status: aceito (30/09/2026)

## Contexto
Uma auditoria independente depois da V1 listou nove casos de borda: estado em segundo plano que se perde com o Redis, entrega ativa sem reentrega, deduplicação só em memória, handoff que some se o registro falhar, lacunas na máscara de PII, pseudônimos sem chave, filtro da frase do LLM, `quote_id` repetido pelo cache e hedging que dobra a carga na lentidão. A restrição: corrigir sem mudar o que já funciona (fluxo, preços, textos, ids das conversas existentes).

## Decisão
- **Segundo plano:** o horário da próxima tentativa também vai para o estado do grafo (`retry_em`, no checkpoint SQLite). Na subida, conversas em `aguardando_cotacao` sem entrada no Redis ganham a tentativa de volta; uma mensagem do lead nessa situação também reconstrói. O Redis do compose passa a ter AOF e volume.
- **Entrega ativa:** falha no Omni ou no webhook vai para um hash de reentrega com backoff (10 s a 15 min, 5 tentativas), só nos destinos que falharam. Eventos `entrega_falhou`, `entrega_reentregue` e `entrega_desistiu` no log de rastreio, sem o texto. A mensagem continua no outbox para o canal buscar.
- **Idempotência:** a resposta de cada `message_id` vindo do canal fica no store (48 h, dentro do lock da conversa), sem o id do canal. A memória segue como atalho.
- **Handoff:** o `handoff_id` nasce no grafo e o registro é idempotente. São 3 tentativas no turno; se todas falharem, a fachada conclui em segundo plano direto na fila (mesmo store), com a pendência persistida. A fila ganhou status: `pendente`, `em_atendimento`, `devolvido`, `encerrado` (hash à parte, sem reescrever a lista).
- **Máscara de PII:** CEP com espaço ou ponto, CNPJ, RG (com a palavra antes), cartão (13 a 19 dígitos com Luhn) e sobrenome depois de "da", "de", "do", "dos", "das".
- **Pseudônimos:** HMAC-SHA256 com `PSEUDONIMO_KEY`. Sem a chave, continua o SHA-256 (compatível com as conversas gravadas) e o agente avisa no log. A base do desafio (`data/`) não muda: é pública e fictícia, e mudar invalidaria a Gold.
- **Frase do LLM:** o filtro passa a barrar valor por extenso e condições comerciais genéricas ("sem carência", "cobre tudo", "parcelar", "imediato"). A troca por frases fixas escolhidas por índice foi rejeitada por agora: a avaliação com Groq mostrou que a frase livre é o que deixa a conversa natural (12 de 14 aproveitadas), e o filtro em camadas mais o guardrail de saída continuam valendo.
- **Rastreio:** cada entrega do cache ganha `quote_id` próprio, com `source_quote_id` apontando para a resposta original da API.
- **Carga no legado:** hedge com orçamento por minuto (10% das cotações, piso de 3) e desligado enquanto houver cotação falhando.

## Consequências
- Mais estado no Redis (dedup, reentrega, status, pendências de handoff): o AOF passa a ser necessário, não opcional.
- `PSEUDONIMO_KEY` entra no passo 2 do README; em instalação já em uso, ligar a chave muda os ids (as conversas antigas não são encontradas). Por isso ela não é obrigatória.
- Nome sem frase de apresentação continua fora da máscara: detectar nome solto por padrão gera falso positivo demais. Fica para um detector com lista de nomes ou NER.
