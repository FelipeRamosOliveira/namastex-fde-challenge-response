# ADR 0005: Valores mostrados vêm só da API

- Status: aceito (29/09/2026)

## Decisão
- `agent/templates.py` monta a mensagem de cotação a partir do dict devolvido pela `/quote`; nenhum número é escrito à mão.
- `guardrails/output.py` extrai todo `R$` da resposta e compara com os valores da API na conversa (prêmio, franquia, pro-rata). Diferente: resposta bloqueada e trocada por mensagem segura.
- O `/planos` é usado para pré-validar regras e listar coberturas, nunca para calcular preço.
- Cache guarda a resposta da API com `quote_id`; a mesma cotação é reapresentada, não recalculada.
- A Gold guarda a resposta da API real (rodada com falha zero) como resultado esperado.

## Consequências
- Na etapa 4 o LLM só escreve texto sem valores; os valores entram pelo template.
- Limite: a frase-ponte do LLM é filtrada por lista de bloqueio (dígito, R$, promessas conhecidas). Depois da auditoria, a lista pega também valor por extenso ("cento e vinte") e condição comercial genérica ("sem carência", "cobre tudo", "parcelar") (ADR 0009). Continua sendo lista de bloqueio: uma formulação nova pode passar, e o guardrail de saída só procura `R$` seguido de número.
