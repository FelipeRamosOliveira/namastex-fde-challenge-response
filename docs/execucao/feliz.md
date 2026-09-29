# Execução completa: feliz

Gerado em 29/09/2026 15:20 por `scripts/exportar_execucao.py` contra a quote-api original (instabilidade padrão: 20% falha, 10% lenta). Texto do lead mascarado no rastreio.

- conversation_ref: `conv_8131a9137eb2c80b`
- estado final: `handoff`
- handoff: `pronto_para_fechar` (`ho_ff6e72b56c3a`)

## Conversa (como o lead viu)

**lead**: Oi, queria fazer um seguro pro meu carro

**agente** [coletando]: Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. Qual é o modelo e o ano do seu carro?

**lead**: é um Toyota Corolla 2019

**agente** [coletando]: E qual é a sua idade?

**lead**: tenho 35 anos, meu cpf é [CPF_1]

**agente** [coletando]: Qual o CEP de onde o carro fica à noite?

**lead**: o carro dorme no cep [CEP_1]

**agente** [coletando]: Temos 3 planos:  
- *Essencial*: colisão, roubo, furto  
- *Completo*: colisão, roubo, furto, danos a terceiros, vidros  
- *Premium*: colisão, roubo, furto, danos a terceiros, vidros, carro reserva, assistência 24h  
Qual deles você quer cotar?

**lead**: quero o completo

**agente** [coletando]: A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10).

**lead**: pode ser a partir do dia 15

**agente** [confirmando]: Só pra confirmar antes de cotar:  
- Carro ano 2019  
- Idade 35 anos  
- CEP da região 26xxx  
- Plano Completo  
- Início em 15/10/2026  
Está certo? (sim / não)

**lead**: sim

**agente** [cotado]: Cotação pronta! Plano *Completo*: R$ 313,80 por mês.  
Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00.  
Atenção: roubo e furto só passam a valer depois de 30 dias de carência.  
Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais.  
Quer fechar com esse plano ou prefere ver outro?

**lead**: fechado!

**agente** [handoff]: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Conversa (como ficou no rastreio, mascarada)

- **lead** `msg_6a7fac965e81`: Oi, queria fazer um seguro pro meu carro
- **agente** `msg_ec166862dcce`: Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. Qual é o modelo e o ano do seu carro?
- **lead** `msg_9cf40ec01bc1`: é um Toyota Corolla 2019
- **agente** `msg_83a6726907b2`: E qual é a sua idade?
- **lead** `msg_f9fff1a92bc1`: tenho 35 anos, meu cpf é [CPF_1]
- **agente** `msg_2beefe522c07`: Qual o CEP de onde o carro fica à noite?
- **lead** `msg_d44d61128d77`: o carro dorme no cep [CEP_1]
- **agente** `msg_98c983056591`: Temos 3 planos: / - *Essencial*: colisão, roubo, furto / - *Completo*: colisão, roubo, furto, danos a terceiros, vidros / - *Premium*: colisão, roubo, furto, danos a terceiros, vidros, carro reserva, assistência 24h / Qual deles você quer cotar?
- **lead** `msg_f6681b61895f`: quero o completo
- **agente** `msg_0a2cb9fc3b84`: A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10).
- **lead** `msg_e70c5123d3af`: pode ser a partir do dia 15
- **agente** `msg_f625c8c36432`: Só pra confirmar antes de cotar: / - Carro ano 2019 / - Idade 35 anos / - CEP da região 26xxx / - Plano Completo / - Início em 15/10/2026 / Está certo? (sim / não)
- **lead** `msg_3244987dc2fa`: sim
- **agente** `msg_70701a3afe02`: Cotação pronta! Plano *Completo*: R$ 313,80 por mês. / Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00. / Atenção: roubo e furto só passam a valer depois de 30 dias de carência. / Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais. / Quer fechar com esse plano ou prefere ver outro?
- **lead** `msg_6705142a3968`: fechado!
- **agente** `msg_f9ee7ce54e25`: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Cotações

| quote_request_id | status | quote_id | prêmio | tentativas (resultado/HTTP/ms) | cache |
|---|---|---|---|---|---|
| `qr_b531d71cfdec` | ok | `q_f9480ff10428` | 313.8 | ok/200/4 | False |

## Eventos

| hora | tipo | message_id | detalhe |
|---|---|---|---|
| 15:20:51.579 | message_in | `msg_6a7fac965e81` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.582 | extracao | `msg_6a7fac965e81` | {"slots": {}, "intents": ["saudacao"], "fonte": "regras"} |
| 15:20:51.585 | message_out | `msg_6a7fac965e81` | {"out_message_id": "msg_ec166862dcce", "stage": "coletando"} |
| 15:20:51.595 | message_in | `msg_9cf40ec01bc1` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.596 | extracao | `msg_9cf40ec01bc1` | {"slots": {"veiculo_ano": "2019"}, "intents": [], "fonte": "regras"} |
| 15:20:51.600 | pre_validacao | `msg_9cf40ec01bc1` | {"ok": true, "regra": null, "motivo": null} |
| 15:20:51.602 | message_out | `msg_9cf40ec01bc1` | {"out_message_id": "msg_83a6726907b2", "stage": "coletando"} |
| 15:20:51.610 | message_in | `msg_f9fff1a92bc1` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.611 | extracao | `msg_f9fff1a92bc1` | {"slots": {"idade": "35"}, "intents": [], "fonte": "regras"} |
| 15:20:51.613 | pre_validacao | `msg_f9fff1a92bc1` | {"ok": true, "regra": null, "motivo": null} |
| 15:20:51.614 | message_out | `msg_f9fff1a92bc1` | {"out_message_id": "msg_2beefe522c07", "stage": "coletando"} |
| 15:20:51.625 | message_in | `msg_d44d61128d77` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.626 | extracao | `msg_d44d61128d77` | {"slots": {"cep": "[CEP_1]"}, "intents": [], "fonte": "regras"} |
| 15:20:51.627 | message_out | `msg_d44d61128d77` | {"out_message_id": "msg_98c983056591", "stage": "coletando"} |
| 15:20:51.638 | message_in | `msg_f6681b61895f` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.639 | extracao | `msg_f6681b61895f` | {"slots": {"plano_id": "completo"}, "intents": [], "fonte": "regras"} |
| 15:20:51.640 | message_out | `msg_f6681b61895f` | {"out_message_id": "msg_0a2cb9fc3b84", "stage": "coletando"} |
| 15:20:51.648 | message_in | `msg_e70c5123d3af` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.649 | extracao | `msg_e70c5123d3af` | {"slots": {"data_inicio": "2026-10-15"}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:51.650 | message_out | `msg_e70c5123d3af` | {"out_message_id": "msg_f625c8c36432", "stage": "confirmando"} |
| 15:20:51.660 | message_in | `msg_3244987dc2fa` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.660 | extracao | `msg_3244987dc2fa` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:51.670 | cotacao | `msg_3244987dc2fa` | {"quote_request_id": "qr_b531d71cfdec", "status": "ok", "quote_id": "q_f9480ff10428", "from_cache": false, "latency_ms": 4.2, "premio_mensal": 313.8} |
| 15:20:51.671 | message_out | `msg_3244987dc2fa` | {"out_message_id": "msg_70701a3afe02", "stage": "cotado"} |
| 15:20:51.681 | message_in | `msg_6705142a3968` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.681 | extracao | `msg_6705142a3968` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:51.687 | handoff | `msg_6705142a3968` | {"motivo": "pronto_para_fechar", "handoff_id": "ho_ff6e72b56c3a", "detalhe": null} |
| 15:20:51.687 | message_out | `msg_6705142a3968` | {"out_message_id": "msg_f9ee7ce54e25", "stage": "handoff"} |

## Checkpoints do LangGraph

42 checkpoints. Nós executados, em ordem:

__start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> handoff -> saida
