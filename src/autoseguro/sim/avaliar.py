"""Roda leads simulados contra o agente e mede o que o desafio avalia.

Métricas:
- ponta_a_ponta: conversas elegíveis que chegaram a uma cotação
- acerto_preco: cotações cujo prêmio mostrado é igual ao da API (Gold) para o plano pedido
- handoff_correto: conversas terminadas em humano com motivo coerente com o caso
  (inelegível -> recusa_regra; ganho -> pronto_para_fechar; perdido -> objecao_preco)
- vazamento_pii: respostas do agente com PII (meta: 0)
- latência por turno (p50, p95) e cotações que saíram em segundo plano

Uso (agente no ar, ex.: Docker):
    uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 50
    uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 5 --lead fastagent
Sem --url, sobe o agente em processo (precisa da quote-api em QUOTE_API_URL).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from autoseguro.agent.templates import brl
from autoseguro.guardrails.pii import mask_dict, scan
from autoseguro.sim.leads import Lead, LeadFastAgent, LeadRoteiro, Persona

ROOT = Path(__file__).resolve().parents[3]
GOLD = ROOT / "data" / "gold" / "cases.jsonl"

Enviar = Callable[[str, str], Awaitable[dict[str, Any]]]
Ativas = Callable[[str], Awaitable[list[dict[str, Any]]]]

MOTIVO_ESPERADO = {
    "ganho": "pronto_para_fechar",
    "perdido": "objecao_preco",
    "em_negociacao": "objecao_preco",
}


async def conversar(
    p: Persona, lead: Lead, enviar: Enviar, ativas: Ativas, max_turnos: int = 16, espera_ativa_s: float = 30.0
) -> dict[str, Any]:
    cid = f"sim-{p.case_id}-{int(time.time() * 1000)}"
    msg = await lead.abrir()
    turnos, lat, respostas, estado, vistas = [], [], [], None, 0
    for _ in range(max_turnos):
        t0 = time.perf_counter()
        r = await enviar(cid, msg)
        lat.append(round((time.perf_counter() - t0) * 1000, 1))
        estado, bot = r.get("stage"), r.get("reply", "")
        respostas.append(bot)
        turnos.append({"lead": msg, "bot": bot, "stage": estado})
        if estado == "aguardando_cotacao":  # espera a mensagem ativa (cotação em segundo plano)
            fim = time.perf_counter() + espera_ativa_s
            while time.perf_counter() < fim:
                novas = (await ativas(cid))[vistas:]
                if novas:
                    vistas += len(novas)
                    bot = novas[-1]["texto"]
                    respostas.append(bot)
                    turnos.append({"ativa": bot})
                    estado = "handoff" if "atendente" in bot else "cotado"
                    break
                await asyncio.sleep(0.2)
        if estado == "handoff":
            break
        nxt = await lead.responder(bot)
        if nxt is None:
            break
        msg = nxt
    cotacoes = [m for m in respostas if "Cotação pronta" in m]
    handoff = r.get("handoff") or {}
    return {
        "conversation_id": cid,
        "persona": p,
        "turnos": turnos,
        "latencias_ms": lat,
        "respostas": respostas,
        "estado_final": estado,
        "motivo_handoff": handoff.get("motivo"),
        "cotacoes": cotacoes,
    }


def _premios_mostrados(texto: str) -> list[str]:
    m = re.search(r"Plano \*(\w+)\*: (R\$ [\d.]+,\d{2}) por mês", texto)
    return [(m.group(1).lower(), m.group(2))] if m else []


def metricas(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    eleg = [r for r in resultados if r["persona"].elegivel]
    chegaram = [r for r in eleg if r["cotacoes"]]
    precos_ok = precos_total = 0
    for r in resultados:
        for c in r["cotacoes"]:
            for plano, valor in _premios_mostrados(c):
                precos_total += 1
                esp = r["persona"].premio_esperado(plano)
                precos_ok += esp is not None and brl(esp) == valor
    handoffs = [r for r in resultados if r["estado_final"] == "handoff"]
    coerentes = 0
    for r in handoffs:
        p = r["persona"]
        esperado = "recusa_regra" if not p.elegivel else MOTIVO_ESPERADO.get(p.desfecho)
        coerentes += r["motivo_handoff"] == esperado or r["motivo_handoff"] == "cotacao_indisponivel"
    vaz = sum(1 for r in resultados for m in r["respostas"] if scan(m))
    lat = sorted(x for r in resultados for x in r["latencias_ms"])
    q = (lambda f: round(lat[min(len(lat) - 1, int(len(lat) * f))], 1)) if lat else (lambda f: None)
    return {
        "conversas": len(resultados),
        "elegiveis": len(eleg),
        "ponta_a_ponta": f"{len(chegaram)}/{len(eleg)}",
        "taxa_ponta_a_ponta": round(len(chegaram) / max(1, len(eleg)), 3),
        "acerto_preco": f"{precos_ok}/{precos_total}",
        "taxa_acerto_preco": round(precos_ok / max(1, precos_total), 3),
        "handoffs": dict(Counter(r["motivo_handoff"] for r in handoffs)),
        "handoff_coerente": f"{coerentes}/{len(handoffs)}",
        "cotacao_em_segundo_plano": sum(1 for r in resultados for t in r["turnos"] if "ativa" in t),
        "vazamento_pii_respostas": vaz,
        "latencia_turno_ms": {
            "p50": q(0.5),
            "p95": q(0.95),
            "max": round(lat[-1], 1) if lat else None,
            "media": round(statistics.mean(lat), 1) if lat else None,
        },
    }


def salvar(caminho: Path, m: dict[str, Any], res: list[dict[str, Any]]) -> None:
    """Grava métricas e conversas; o texto das conversas sai mascarado (vai para o repo)."""
    conversas = [
        {k: v for k, v in r.items() if k != "persona"}
        | {
            "case_id": r["persona"].case_id,
            "desfecho": r["persona"].desfecho,
            "elegivel": r["persona"].elegivel,
        }
        for r in res
    ]
    caminho.write_text(
        json.dumps(
            {"metricas": m, "conversas": mask_dict(conversas)}, ensure_ascii=False, indent=1, default=str
        ),
        encoding="utf-8",
    )


def carregar_gold(n: int) -> list[dict[str, Any]]:
    casos = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    return casos[:n]


async def avaliar(
    enviar: Enviar, ativas: Ativas, n: int = 50, lead: str = "roteiro", concorrencia: int = 8
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sem = asyncio.Semaphore(concorrencia)

    async def um(caso):
        p = Persona.from_gold(caso)
        ld = LeadFastAgent(p) if lead == "fastagent" else LeadRoteiro(p)
        async with sem:
            try:
                return await conversar(p, ld, enviar, ativas)
            finally:
                if isinstance(ld, LeadFastAgent):
                    await ld.fechar()

    resultados = await asyncio.gather(*[um(c) for c in carregar_gold(n)])
    return metricas(resultados), resultados


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="agente no ar (ex.: http://localhost:8080)")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--lead", choices=["roteiro", "fastagent"], default="roteiro")
    ap.add_argument("--saida", default=str(ROOT / "docs" / "avaliacao.json"))
    a = ap.parse_args()

    async def run():
        async with httpx.AsyncClient(base_url=a.url, timeout=60) as c:

            async def enviar(cid, texto):
                return (await c.post("/v1/messages", json={"conversation_id": cid, "text": texto})).json()

            async def ativas(cid):
                return (await c.get(f"/v1/conversations/{cid}/outbox")).json()

            return await avaliar(enviar, ativas, a.n, a.lead)

    m, res = asyncio.run(run())
    salvar(Path(a.saida), m, res)
    print(json.dumps(m, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
