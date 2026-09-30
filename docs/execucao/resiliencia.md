# Execução completa: resiliencia

Gerado em 29/09/2026 16:11 por `scripts/exportar_execucao.py` contra a quote-api original (instabilidade padrão: 20% falha, 10% lenta). Texto do lead mascarado no rastreio.

> **Falha injetada:** no "sim", o cliente HTTP do teste devolve 503 em toda chamada à `/quote` (transporte `Interruptor` em `scripts/exportar_execucao.py`) até o agente avisar o lead; um segundo depois a API volta e a primeira tentativa em segundo plano entrega a cotação. Assim a execução mostra sempre o mesmo caminho: tentativas rápidas, aviso ao lead e cotação em segundo plano. Os intervalos do segundo plano foram encurtados para 2, 5 e 10 s (no serviço são 5, 20 e 60 s). A chamada lenta de 8 s cortada pelo hedging não aparece aqui; ela é coberta pelos testes de `tests/unit/test_quote_client.py` e `tests/integration/test_quote_real.py`.

- conversation_ref: `conv_962def31ed4dfe5c`
- estado final: `handoff`
- handoff: `pronto_para_fechar` (`ho_eada168845d4`)

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

- **lead** `msg_bc752aef21cd`: Oi, queria fazer um seguro pro meu carro
- **agente** `msg_5e399d70a671`: Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro. Qual é o modelo e o ano do seu carro?
- **lead** `msg_0bb81edf28ba`: é um Toyota Corolla 2019
- **agente** `msg_cca8ae011f68`: E qual é a sua idade?
- **lead** `msg_a5e0c834ae5f`: tenho 35 anos, meu cpf é [CPF_1]
- **agente** `msg_dc4af667de76`: Qual o CEP de onde o carro fica à noite?
- **lead** `msg_79e1e205aa4b`: o carro dorme no cep [CEP_1]
- **agente** `msg_cde12e9012e6`: Temos 3 planos: / - *Essencial*: colisão, roubo, furto / - *Completo*: colisão, roubo, furto, danos a terceiros, vidros / - *Premium*: colisão, roubo, furto, danos a terceiros, vidros, carro reserva, assistência 24h / Qual deles você quer cotar?
- **lead** `msg_9a9b3aa49e9d`: quero o completo
- **agente** `msg_620ab47bc19a`: A partir de quando você quer o seguro? Pode ser hoje ou uma data (ex.: 15/10).
- **lead** `msg_074cee28d11d`: pode ser a partir do dia 15
- **agente** `msg_a18e40bac341`: Só pra confirmar antes de cotar: / - Carro ano 2019 / - Idade 35 anos / - CEP da região 26xxx / - Plano Completo / - Início em 15/10/2026 / Está certo? (sim / não)
- **lead** `msg_5451ee400bbf`: sim
- **agente** `msg_0b3438cef8cc`: O sistema de cotação está instável agora e eu não vou te passar um valor sem ter certeza. Já estou tentando de novo e te mando a cotação aqui assim que sair.
- **agente** `msg_de3adc135bf3`: Consegui! Cotação pronta! Plano *Completo*: R$ 313,80 por mês. / Coberturas: colisão, roubo, furto, danos a terceiros, vidros. Franquia de R$ 3.000,00. / Atenção: roubo e furto só passam a valer depois de 30 dias de carência. / Como o início é no meio do mês, o primeiro pagamento é proporcional: R$ 172,08 (17 de 31 dias). Os meses seguintes são integrais. / Quer fechar com esse plano ou prefere ver outro?
- **lead** `msg_965713ac74b1`: fechado!
- **agente** `msg_27df861fd72d`: Ótimo! Um consultor vai te chamar em seguida pra emitir a apólice e o boleto, com a cotação que acabamos de fazer.

## Cotações

| quote_request_id | status | quote_id | prêmio | tentativas (resultado/HTTP/ms) | cache |
|---|---|---|---|---|---|
| `qr_3add0030caf9` | indisponivel | `None` | None | erro_5xx/503/0, erro_5xx/503/0, erro_5xx/503/0, erro_5xx/503/1 | False |
| `qr_ad215ba5afc9` | ok | `q_217e34c1cff4` | 313.8 | ok/200/3 | False |

## Eventos

| hora | tipo | message_id | detalhe |
|---|---|---|---|
| 16:11:05.681 | message_in | `msg_bc752aef21cd` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.682 | extracao | `msg_bc752aef21cd` | {"slots": {}, "intents": ["saudacao"], "fonte": "regras"} |
| 16:11:05.685 | message_out | `msg_bc752aef21cd` | {"out_message_id": "msg_5e399d70a671", "stage": "coletando"} |
| 16:11:05.693 | message_in | `msg_0bb81edf28ba` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.694 | extracao | `msg_0bb81edf28ba` | {"slots": {"veiculo_ano": "2019"}, "intents": [], "fonte": "regras"} |
| 16:11:05.697 | pre_validacao | `msg_0bb81edf28ba` | {"ok": true, "regra": null, "motivo": null} |
| 16:11:05.698 | message_out | `msg_0bb81edf28ba` | {"out_message_id": "msg_cca8ae011f68", "stage": "coletando"} |
| 16:11:05.707 | message_in | `msg_a5e0c834ae5f` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.707 | extracao | `msg_a5e0c834ae5f` | {"slots": {"idade": "35"}, "intents": [], "fonte": "regras"} |
| 16:11:05.709 | pre_validacao | `msg_a5e0c834ae5f` | {"ok": true, "regra": null, "motivo": null} |
| 16:11:05.710 | message_out | `msg_a5e0c834ae5f` | {"out_message_id": "msg_dc4af667de76", "stage": "coletando"} |
| 16:11:05.720 | message_in | `msg_79e1e205aa4b` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.720 | extracao | `msg_79e1e205aa4b` | {"slots": {"cep": "[CEP_1]"}, "intents": [], "fonte": "regras"} |
| 16:11:05.722 | message_out | `msg_79e1e205aa4b` | {"out_message_id": "msg_cde12e9012e6", "stage": "coletando"} |
| 16:11:05.743 | message_in | `msg_9a9b3aa49e9d` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.743 | extracao | `msg_9a9b3aa49e9d` | {"slots": {"plano_id": "completo"}, "intents": [], "fonte": "regras"} |
| 16:11:05.744 | message_out | `msg_9a9b3aa49e9d` | {"out_message_id": "msg_620ab47bc19a", "stage": "coletando"} |
| 16:11:05.753 | message_in | `msg_074cee28d11d` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.754 | extracao | `msg_074cee28d11d` | {"slots": {"data_inicio": "2026-10-15"}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:05.755 | message_out | `msg_074cee28d11d` | {"out_message_id": "msg_a18e40bac341", "stage": "confirmando"} |
| 16:11:05.767 | message_in | `msg_5451ee400bbf` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:05.768 | extracao | `msg_5451ee400bbf` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:05.922 | cotacao | `msg_5451ee400bbf` | {"quote_request_id": "qr_3add0030caf9", "status": "indisponivel", "quote_id": null, "from_cache": false, "latency_ms": 147.8, "premio_mensal": null} |
| 16:11:05.922 | retry_agendado | `msg_5451ee400bbf` | {"em_s": 2.0, "tentativa_fundo": 1} |
| 16:11:05.924 | message_out | `msg_5451ee400bbf` | {"out_message_id": "msg_0b3438cef8cc", "stage": "aguardando_cotacao"} |
| 16:11:07.935 | evento_sistema | `sys_d42cfb290dfd` | {"evento": "retentar_cotacao"} |
| 16:11:07.942 | cotacao | `sys_d42cfb290dfd` | {"quote_request_id": "qr_ad215ba5afc9", "status": "ok", "quote_id": "q_217e34c1cff4", "from_cache": false, "latency_ms": 3.2, "premio_mensal": 313.8} |
| 16:11:07.943 | message_out | `sys_d42cfb290dfd` | {"out_message_id": "msg_de3adc135bf3", "stage": "cotado"} |
| 16:11:08.141 | message_in | `msg_965713ac74b1` | {"pii_detectada": [], "message_type": "text"} |
| 16:11:08.142 | extracao | `msg_965713ac74b1` | {"slots": {}, "intents": ["aceite"], "fonte": "regras"} |
| 16:11:08.147 | handoff | `msg_965713ac74b1` | {"motivo": "pronto_para_fechar", "handoff_id": "ho_eada168845d4", "detalhe": null} |
| 16:11:08.148 | message_out | `msg_965713ac74b1` | {"out_message_id": "msg_27df861fd72d", "stage": "handoff"} |

## Checkpoints do LangGraph

48 checkpoints. Nós executados, em ordem:

__start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> cotar -> saida -> __start__ -> entrada -> decidir -> handoff -> saida
