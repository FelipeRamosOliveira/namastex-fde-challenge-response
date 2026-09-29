# Execução completa: feliz

Gerado em 29/09/2026 16:11 por `scripts/exportar_execucao.py` contra a quote-api original (instabilidade padrão: 20% falha, 10% lenta). Texto do lead mascarado no rastreio.

- conversation_ref: `conv_8131a9137eb2c80b`
- estado final: `handoff`
- handoff: `pronto_para_fechar` (`ho_91383a2554dc`)

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

- **lead** `msg_a8a13e2bf8a1`: Oi, queria fazer um seguro pro meu carro
- **agente** `msg_7b704abdf5c9`: Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. Qual é o modelo e o ano do seu carro?
- **lead** `msg_8b0cf9f09ee4`: é um Toyota Corolla 2019
- **agente** `msg_f6e913b5afdc`: E qual é a sua idade?
- **lead** `msg_b15746217b39`: tenho 35 anos, meu cpf é [CPF_1]
- **agente** `msg_f3ade0469443`: Qual o CEP de onde o carro fica à noite?
- **lead** `msg_ceab14641bed`: o carro dorme no cep [CEP_1]
- **agente** `msg_ec957a3b18db`: Temos 3 planos: / - *Essencial*: colisão, roubo, furto / - *Completo*: colisão, roubo, furto, danos a terceiros, vidros / - *Premium*: colisão, roubo, furto, danos a terceiros, vidros, carro reserva, assistência 24h / Qual deles você quer cotar?
- **lead** `msg_341da972d654`: quero o completo
- **agente** `msg_8a98776a298a`: A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10).
- **lead** `msg_d47899443b57`: pode ser a partir do dia 15
- **agente** `msg_02e00df67022`: Só pra confirmar antes de cotar: / - Carro ano 2019 / - Idade 35 anos / - CEP da região 26xxx / - Plano Completo / - Início em 15/10/2026 / Está certo? (sim / não)
- **lead** `msg_9f38be650905`: sim
- **agente** `msg_9d8a90452747`: Cotação pronta! Plano *Completo*: R$ 313,80 por mês. / Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00. / Atenção: roubo e furto só passam a valer depois de 30 dias de carência. / Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais. / Quer fechar com esse plano ou prefere ver outro?
- **lead** `msg_2f96aad1c879`: fechado!
- **agente** `msg_355d2c921e4b`: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Cotações

| quote_request_id | status | quote_id | prêmio | tentativas (resultado/HTTP/ms) | cache |
|---|---|---|---|---|---|
| `qr_a5053c64d450` | ok | `q_1a978c97c19c` | 313.8 | erro_5xx/503/3, ok/200/4 | False |

## Eventos

| hora | tipo | message_id | detalhe |
|---|---|---|---|
| 16:11:05.328 | message_in | `msg_a8a13e2bf8a1` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.330 | extracao | `msg_a8a13e2bf8a1` | {"slots": {}, "intents": ["saudacao"], "fonte": "regras"} |
| 16:11:05.334 | message_out | `msg_a8a13e2bf8a1` | {"out_message_id": "msg_7b704abdf5c9", "stage": "coletando"} |
| 16:11:05.345 | message_in | `msg_8b0cf9f09ee4` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.346 | extracao | `msg_8b0cf9f09ee4` | {"slots": {"veiculo_ano": "2019"}, "intents": [], "fonte": "regras"} |
| 16:11:05.350 | pre_validacao | `msg_8b0cf9f09ee4` | {"ok": true, "regra": null, "motivo": null} |
| 16:11:05.351 | message_out | `msg_8b0cf9f09ee4` | {"out_message_id": "msg_f6e913b5afdc", "stage": "coletando"} |
| 16:11:05.360 | message_in | `msg_b15746217b39` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.361 | extracao | `msg_b15746217b39` | {"slots": {"idade": "35"}, "intents": [], "fonte": "regras"} |
| 16:11:05.362 | pre_validacao | `msg_b15746217b39` | {"ok": true, "regra": null, "motivo": null} |
| 16:11:05.364 | message_out | `msg_b15746217b39` | {"out_message_id": "msg_f3ade0469443", "stage": "coletando"} |
| 16:11:05.372 | message_in | `msg_ceab14641bed` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.373 | extracao | `msg_ceab14641bed` | {"slots": {"cep": "[CEP_1]"}, "intents": [], "fonte": "regras"} |
| 16:11:05.374 | message_out | `msg_ceab14641bed` | {"out_message_id": "msg_ec957a3b18db", "stage": "coletando"} |
| 16:11:05.382 | message_in | `msg_341da972d654` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.383 | extracao | `msg_341da972d654` | {"slots": {"plano_id": "completo"}, "intents": [], "fonte": "regras"} |
| 16:11:05.384 | message_out | `msg_341da972d654` | {"out_message_id": "msg_8a98776a298a", "stage": "coletando"} |
| 16:11:05.393 | message_in | `msg_d47899443b57` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.394 | extracao | `msg_d47899443b57` | {"slots": {"data_inicio": "2026-10-15"}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:05.395 | message_out | `msg_d47899443b57` | {"out_message_id": "msg_02e00df67022", "stage": "confirmando"} |
| 16:11:05.405 | message_in | `msg_9f38be650905` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.405 | extracao | `msg_9f38be650905` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:05.510 | cotacao | `msg_9f38be650905` | {"quote_request_id": "qr_a5053c64d450", "status": "ok", "quote_id": "q_1a978c97c19c", "from_cache": false, "latency_ms": 99.1, "premio_mensal": 313.8} |
| 16:11:05.512 | message_out | `msg_9f38be650905` | {"out_message_id": "msg_9d8a90452747", "stage": "cotado"} |
| 16:11:05.522 | message_in | `msg_2f96aad1c879` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.523 | extracao | `msg_2f96aad1c879` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:05.528 | handoff | `msg_2f96aad1c879` | {"motivo": "pronto_para_fechar", "handoff_id": "ho_91383a2554dc", "detalhe": null} |
| 16:11:05.529 | message_out | `msg_2f96aad1c879` | {"out_message_id": "msg_355d2c921e4b", "stage": "handoff"} |

## Checkpoints do LangGraph

42 checkpoints. Nós executados, em ordem:

__start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> handoff -> saida
