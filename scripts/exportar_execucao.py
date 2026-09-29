"""Gera o log de execução completa pedido no desafio (uma conversa do início ao fim, com a cotação saindo).

Roda o agente EM PROCESSO contra a quote-api original (com a instabilidade padrão) e exporta:
  docs/execucao/<cenario>.jsonl   eventos de rastreio (1 por linha), já mascarados
  docs/execucao/<cenario>.md      versão legível: conversa, eventos, tentativas, checkpoints
Cenários:
  feliz        lead completo até fechar
  resiliencia  a /quote cai no meio; o lead recebe a cotação em segundo plano quando ela volta
Ao final, o scanner de PII roda nos arquivos gerados.

Uso: (quote-api no ar) uv run python scripts/exportar_execucao.py --quote-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoseguro.agent.service import AutoSeguroAgent  # noqa: E402
from autoseguro.config import Settings  # noqa: E402
from autoseguro.guardrails.pii import PiiVault, mask, scan  # noqa: E402
from autoseguro.tools.mcp_server import Services  # noqa: E402
from autoseguro.tools.store import MemoryStore  # noqa: E402

OUT = ROOT / "docs" / "execucao"
ROTEIRO = [
    "Oi, queria fazer um seguro pro meu carro",
    "é um Toyota Corolla 2019",
    "tenho 35 anos, meu cpf é 389.083.863-43",
    "o carro dorme no cep 26703-384",
    "quero o completo",
    "pode ser a partir do dia 15",
    "sim",
    "fechado!",
]


class Interruptor(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.fora = False
        self.real = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        if self.fora and request.url.path == "/quote":
            return httpx.Response(503, json={"error": "upstream_unavailable"})
        return await self.real.handle_async_request(request)


async def rodar(cenario: str, quote_url: str) -> Path:
    s = Settings(
        _env_file=None,
        quote_api_url=quote_url,
        checkpoint_db=tempfile.mktemp(suffix=".sqlite"),
        retry_fundo_delays_s=[2.0, 5.0, 10.0],
    )
    chave = Interruptor()
    http = httpx.AsyncClient(base_url=quote_url, transport=chave)
    services = Services.from_settings(s, store=MemoryStore(), http=http)
    cid = f"execucao-{cenario}"
    linhas = []
    vault = PiiVault()  # a versão "como o lead viu" também sai mascarada
    async with AutoSeguroAgent(s, services=services) as ag:
        for msg in ROTEIRO:
            if cenario == "resiliencia" and msg == "sim":
                chave.fora = True
            r = await ag.handle(cid, msg)
            linhas.append(("lead", mask(msg, vault).text, None))
            linhas.append(("agente", r["reply"], r["stage"]))
            if r["stage"] == "aguardando_cotacao":
                await asyncio.sleep(1.0)
                chave.fora = False  # a API volta; a nova tentativa em segundo plano entrega a cotação
                for _ in range(100):
                    ativas = await ag.mensagens_ativas(cid)
                    if ativas:
                        linhas.append(("agente (mensagem ativa)", ativas[-1]["texto"], "cotado"))
                        break
                    await asyncio.sleep(0.2)
            if r["stage"] == "handoff":
                break
        trace = await ag.trace(cid)
        hist = await ag.historico(cid)

    OUT.mkdir(parents=True, exist_ok=True)
    jl = OUT / f"{cenario}.jsonl"
    jl.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in trace["events"]) + "\n",
        encoding="utf-8",
    )

    md = [
        f"# Execução completa: {cenario}",
        "",
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M} por `scripts/exportar_execucao.py` contra a quote-api "
        "original (instabilidade padrão: 20% falha, 10% lenta). Texto do lead mascarado no rastreio.",
        "",
        f"- conversation_ref: `{trace['conversation_ref']}`",
        f"- estado final: `{trace['stage']}`",
        f"- handoff: `{(trace['handoff'] or {}).get('motivo')}` (`{(trace['handoff'] or {}).get('handoff_id')}`)",
        "",
        "## Conversa (como o lead viu)",
        "",
    ]
    md += [
        f"**{quem}**{f' [{st}]' if st else ''}: {txt}".replace("\n", "  \n") + "\n"
        for quem, txt, st in linhas
    ]
    md += ["## Conversa (como ficou no rastreio, mascarada)", ""]
    md += [
        f"- **{m['role']}** `{m['message_id']}`: {m['text']}".replace("\n", " / ")
        for m in trace["transcript"]
    ]
    md += [
        "",
        "## Cotações",
        "",
        "| quote_request_id | status | quote_id | prêmio | tentativas (resultado/HTTP/ms) | cache |",
        "|---|---|---|---|---|---|",
    ]
    for e in trace["events"]:
        if e["type"] == "cotacao":
            tent = (
                ", ".join(
                    f"{a['outcome']}/{a['http_status']}/{a['latency_ms']:.0f}"
                    + (" hedge" if a["hedge"] else "")
                    for a in e["attempts"]
                )
                or "-"
            )
            md.append(
                f"| `{e['quote_request_id']}` | {e['status']} | `{e.get('quote_id')}` | {e.get('premio_mensal')} "
                f"| {tent} | {e.get('from_cache')} |"
            )
    md += ["", "## Eventos", "", "| hora | tipo | message_id | detalhe |", "|---|---|---|---|"]
    for e in trace["events"]:
        det = {
            k: v
            for k, v in e.items()
            if k not in ("event_id", "ts", "conversation_id", "message_id", "type", "attempts", "text")
        }
        md.append(
            f"| {e['ts'][11:23]} | {e['type']} | `{e.get('message_id')}` | "
            f"{json.dumps(det, ensure_ascii=False, default=str)[:160].replace('|', '/')} |"
        )
    md += [
        "",
        "## Checkpoints do LangGraph",
        "",
        f"{len(hist)} checkpoints. Nós executados, em ordem:",
        "",
        " -> ".join(n for p in hist for n in p["executou"]),
    ]
    mdp = OUT / f"{cenario}.md"
    mdp.write_text("\n".join(md) + "\n", encoding="utf-8")

    vaz = [(f.name, e.kind) for f in (jl, mdp) for e in scan(f.read_text(encoding="utf-8"))]
    print(
        f"{cenario}: {trace['stage']}, {len(trace['events'])} eventos -> {mdp.relative_to(ROOT)}; PII: {vaz or 'nenhuma'}"
    )
    if vaz:
        raise SystemExit("PII no log exportado")
    return mdp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quote-url", default="http://localhost:8000")
    ap.add_argument("--cenario", choices=["feliz", "resiliencia", "todos"], default="todos")
    a = ap.parse_args()
    for c in ["feliz", "resiliencia"] if a.cenario == "todos" else [a.cenario]:
        asyncio.run(rodar(c, a.quote_url))


if __name__ == "__main__":
    main()
