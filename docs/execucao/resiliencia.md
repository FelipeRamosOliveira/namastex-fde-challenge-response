# Execução completa: resiliencia

Gerado em 29/09/2026 15:20 por `scripts/exportar_execucao.py` contra a quote-api original (instabilidade padrão: 20% falha, 10% lenta). Texto do lead mascarado no rastreio.

- conversation_ref: `conv_962def31ed4dfe5c`
- estado final: `handoff`
- handoff: `pronto_para_fechar` (`ho_2056844f57e9`)

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

**agente** [aguardando_cotacao]: O sistema de cotação está instável agora e eu não vou te passar um valor sem ter certeza. Já estou tentando de novo e te mando a cotação aqui assim que sair.

**agente (mensagem ativa)** [cotado]: Consegui! Cotação pronta! Plano *Completo*: R$ 313,80 por mês.  
Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00.  
Atenção: roubo e furto só passam a valer depois de 30 dias de carência.  
Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais.  
Quer fechar com esse plano ou prefere ver outro?

**lead**: fechado!

**agente** [handoff]: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Conversa (como ficou no rastreio, mascarada)

- **lead** `msg_a6593750dcf4`: Oi, queria fazer um seguro pro meu carro
- **agente** `msg_eb96b2431278`: Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. Qual é o modelo e o ano do seu carro?
- **lead** `msg_9fb0783d5287`: é um Toyota Corolla 2019
- **agente** `msg_c316d3b1a984`: E qual é a sua idade?
- **lead** `msg_5ca801c20ec9`: tenho 35 anos, meu cpf é [CPF_1]
- **agente** `msg_a73f4ef8882c`: Qual o CEP de onde o carro fica à noite?
- **lead** `msg_760b592b5d02`: o carro dorme no cep [CEP_1]
- **agente** `msg_f98f45a01e4f`: Temos 3 planos: / - *Essencial*: colisão, roubo, furto / - *Completo*: colisão, roubo, furto, danos a terceiros, vidros / - *Premium*: colisão, roubo, furto, danos a terceiros, vidros, carro reserva, assistência 24h / Qual deles você quer cotar?
- **lead** `msg_faa2d7098f59`: quero o completo
- **agente** `msg_734dd3e7227c`: A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10).
- **lead** `msg_192b2c07896f`: pode ser a partir do dia 15
- **agente** `msg_b6c0bbf0830f`: Só pra confirmar antes de cotar: / - Carro ano 2019 / - Idade 35 anos / - CEP da região 26xxx / - Plano Completo / - Início em 15/10/2026 / Está certo? (sim / não)
- **lead** `msg_02df60b9f10c`: sim
- **agente** `msg_eb2126c0f4d6`: O sistema de cotação está instável agora e eu não vou te passar um valor sem ter certeza. Já estou tentando de novo e te mando a cotação aqui assim que sair.
- **agente** `msg_c23dd220b7b4`: Consegui! Cotação pronta! Plano *Completo*: R$ 313,80 por mês. / Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00. / Atenção: roubo e furto só passam a valer depois de 30 dias de carência. / Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais. / Quer fechar com esse plano ou prefere ver outro?
- **lead** `msg_3d2bb473b70b`: fechado!
- **agente** `msg_4dded60d7aa6`: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Cotações

| quote_request_id | status | quote_id | prêmio | tentativas (resultado/HTTP/ms) | cache |
|---|---|---|---|---|---|
| `qr_0d02dbd6634d` | indisponivel | `None` | None | erro_5xx/503/0, erro_5xx/503/1, erro_5xx/503/1, erro_5xx/503/1 | False |
| `qr_0494fabf3503` | ok | `q_099c71f8e1d5` | 313.8 | erro_5xx/502/3, ok/200/4 | False |

## Eventos

| hora | tipo | message_id | detalhe |
|---|---|---|---|
| 15:20:51.803 | message_in | `msg_a6593750dcf4` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.804 | extracao | `msg_a6593750dcf4` | {"slots": {}, "intents": ["saudacao"], "fonte": "regras"} |
| 15:20:51.807 | message_out | `msg_a6593750dcf4` | {"out_message_id": "msg_eb96b2431278", "stage": "coletando"} |
| 15:20:51.817 | message_in | `msg_9fb0783d5287` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.818 | extracao | `msg_9fb0783d5287` | {"slots": {"veiculo_ano": "2019"}, "intents": [], "fonte": "regras"} |
| 15:20:51.822 | pre_validacao | `msg_9fb0783d5287` | {"ok": true, "regra": null, "motivo": null} |
| 15:20:51.823 | message_out | `msg_9fb0783d5287` | {"out_message_id": "msg_c316d3b1a984", "stage": "coletando"} |
| 15:20:51.833 | message_in | `msg_5ca801c20ec9` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.834 | extracao | `msg_5ca801c20ec9` | {"slots": {"idade": "35"}, "intents": [], "fonte": "regras"} |
| 15:20:51.836 | pre_validacao | `msg_5ca801c20ec9` | {"ok": true, "regra": null, "motivo": null} |
| 15:20:51.837 | message_out | `msg_5ca801c20ec9` | {"out_message_id": "msg_a73f4ef8882c", "stage": "coletando"} |
| 15:20:51.846 | message_in | `msg_760b592b5d02` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.847 | extracao | `msg_760b592b5d02` | {"slots": {"cep": "[CEP_1]"}, "intents": [], "fonte": "regras"} |
| 15:20:51.848 | message_out | `msg_760b592b5d02` | {"out_message_id": "msg_f98f45a01e4f", "stage": "coletando"} |
| 15:20:51.857 | message_in | `msg_faa2d7098f59` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.858 | extracao | `msg_faa2d7098f59` | {"slots": {"plano_id": "completo"}, "intents": [], "fonte": "regras"} |
| 15:20:51.859 | message_out | `msg_faa2d7098f59` | {"out_message_id": "msg_734dd3e7227c", "stage": "coletando"} |
| 15:20:51.868 | message_in | `msg_192b2c07896f` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.869 | extracao | `msg_192b2c07896f` | {"slots": {"data_inicio": "2026-10-15"}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:51.870 | message_out | `msg_192b2c07896f` | {"out_message_id": "msg_b6c0bbf0830f", "stage": "confirmando"} |
| 15:20:51.880 | message_in | `msg_02df60b9f10c` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:51.880 | extracao | `msg_02df60b9f10c` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:52.629 | cotacao | `msg_02df60b9f10c` | {"quote_request_id": "qr_0d02dbd6634d", "status": "indisponivel", "quote_id": null, "from_cache": false, "latency_ms": 742.8, "premio_mensal": null} |
| 15:20:52.629 | retry_agendado | `msg_02df60b9f10c` | {"em_s": 2.0, "tentativa_fundo": 1} |
| 15:20:52.630 | message_out | `msg_02df60b9f10c` | {"out_message_id": "msg_eb2126c0f4d6", "stage": "aguardando_cotacao"} |
| 15:20:54.642 | evento_sistema | `sys_741a45babf0f` | {"evento": "retentar_cotacao"} |
| 15:20:54.832 | cotacao | `sys_741a45babf0f` | {"quote_request_id": "qr_0494fabf3503", "status": "ok", "quote_id": "q_099c71f8e1d5", "from_cache": false, "latency_ms": 184.0, "premio_mensal": 313.8} |
| 15:20:54.834 | message_out | `sys_741a45babf0f` | {"out_message_id": "msg_c23dd220b7b4", "stage": "cotado"} |
| 15:20:55.045 | message_in | `msg_3d2bb473b70b` | {"pii_detectada": [], "message_type": "text"} |
| 15:20:55.046 | extracao | `msg_3d2bb473b70b` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 15:20:55.052 | handoff | `msg_3d2bb473b70b` | {"motivo": "pronto_para_fechar", "handoff_id": "ho_2056844f57e9", "detalhe": null} |
| 15:20:55.053 | message_out | `msg_3d2bb473b70b` | {"out_message_id": "msg_4dded60d7aa6", "stage": "handoff"} |

## Checkpoints do LangGraph

48 checkpoints. Nós executados, em ordem:

__start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> handoff -> saida
