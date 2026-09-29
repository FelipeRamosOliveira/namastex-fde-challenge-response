# Figuras da documentação

Diagramas usados no `README.md` do projeto. Os PNGs são gerados; não edite à mão.

| Figura | O que mostra |
|---|---|
| `01-visao-geral.png` | Containers, canal Omni, LLM e quote-api |
| `02-grafo-langgraph.png` | Nós do grafo do atendimento e o humano no circuito |
| `03-resiliencia-cotacao.png` | Cache, circuit breaker, hedging, retry e cotação em segundo plano |
| `04-pii.png` | Onde o dado pessoal é mascarado e onde o CEP real é usado |
| `05-dados-avaliacao.png` | Pipeline Bronze, Silver e Gold e o simulador de avaliação |

## Fontes (`fonte/`)
- `*.yaml`: spec de cada diagrama (fonte da verdade). Renderizada com o `render.mjs` da skill de arquitetura agnóstica (ELK para layout, ícones genéricos e logos do Simple Icons).
- `*.drawio`: versão editável no draw.io, com os ícones embutidos.

Para mudar um diagrama: edite o `.yaml`, renderize de novo e substitua o PNG.
