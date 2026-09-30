"""Roda leads simulados contra o agente e mede o que o desafio avalia.

Métricas:
- ponta_a_ponta: conversas elegíveis que chegaram a uma cotação
- acerto_preco: cotações cujo prêmio mostrado é igual ao da API (Gold) para o plano pedido
- handoff_correto: conversas terminadas em humano com motivo coerente com o caso
  (inelegível -> recusa_regra; ganho -> pronto_para_fechar; perdido -> objecao_preco).
  Handoff por `cotacao_indisponivel` (API fora mesmo depois das tentativas em segundo plano)
  não entra na conta de coerência: é contado à parte.
- vazamento_pii: respostas do agente com PII (meta: 0)
- latência por turno (p50, p95) e cotações que saíram em segundo plano

Uso (agente no ar, ex.: Docker; lê CHANNEL_API_KEY do ambiente ou --channel-key):
    uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 50
    uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 5 --lead fastagent
    uv run python -m autoseguro.sim.avaliar --url http://localhost:8080 --n 20 --aleatorio 7 --lead fastagent
Sem --url, sobe o agente em processo (precisa da quote-api em QUOTE_API_URL).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
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

# espera pela mensagem ativa: cobre as tentativas em segundo plano padrão (5 + 20 + 60 s) com folga
ESPERA_ATIVA_S = 100.0

MOTIVO_ESPERADO = {
    "ganho": "pronto_para_fechar",
    "perdido": "objecao_preco",
    "em_negociacao": "objecao_preco",
}


async def conversar(
    p: Persona,
    lead: Lead,
    enviar: Enviar,
    ativas: Ativas,
    max_turnos: int = 16,
    espera_ativa_s: float = ESPERA_ATIVA_S,
    pausa_s: float = 0.0,
) -> dict[str, Any]:
    cid = f"sim-{p.case_id}-{int(time.time() * 1000)}"
    msg = await lead.abrir()
    turnos, lat, respostas, estado, vistas, motivo = [], [], [], None, 0, None
    for _ in range(max_turnos):
        t0 = time.perf_counter()
        r = await enviar(cid, msg)
        lat.append(round((time.perf_counter() - t0) * 1000, 1))
        estado, bot = r.get("stage"), r.get("reply", "")
        motivo = (r.get("handoff") or {}).get("motivo") or motivo
        respostas.append(bot)
        turnos.append({"lead": msg, "bot": bot, "stage": estado})
        if estado == "aguardando_cotacao":  # espera a mensagem ativa (cotação em segundo plano)
            fim = time.perf_counter() + espera_ativa_s
            while time.perf_counter() < fim:
                novas = (await ativas(cid))[vistas:]
                if novas:  # o item traz o estágio e o motivo do handoff (sem adivinhar pelo texto)
                    vistas += len(novas)
                    ult = novas[-1]
                    bot = ult["texto"]
                    respostas.append(bot)
                    turnos.append({"ativa": bot})
                    estado = ult.get("stage") or estado
                    motivo = ult.get("motivo_handoff") or motivo
                    break
                await asyncio.sleep(0.2)
        if estado == "handoff":
            break
        nxt = await lead.responder(bot)
        if nxt is None:
            break
        msg = nxt
        await asyncio.sleep(pausa_s)  # tempo de uma pessoa ler e digitar (não estoura a cota do LLM)
    cotacoes = [m for m in respostas if "Cotação pronta" in m]
    return {
        "conversation_id": cid,
        "persona": p,
        "turnos": turnos,
        "latencias_ms": lat,
        "respostas": respostas,
        "estado_final": estado,
        "motivo_handoff": motivo if estado == "handoff" else None,
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
    julgaveis = [r for r in handoffs if r["motivo_handoff"] != "cotacao_indisponivel"]
    coerentes = 0
    for r in julgaveis:
        p = r["persona"]
        esperado = "recusa_regra" if not p.elegivel else MOTIVO_ESPERADO.get(p.desfecho)
        coerentes += r["motivo_handoff"] == esperado
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
        "handoff_coerente": f"{coerentes}/{len(julgaveis)}",
        "handoff_api_indisponivel": len(handoffs) - len(julgaveis),
        "sem_desfecho": sum(1 for r in resultados if r["estado_final"] == "aguardando_cotacao"),
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


def carregar_gold(n: int, semente: int | None = None) -> list[dict[str, Any]]:
    """Os n primeiros casos ou, com semente, uma amostra aleatória reprodutível."""
    casos = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    if semente is None:
        return casos[:n]
    return random.Random(semente).sample(casos, min(n, len(casos)))  # noqa: S311 - amostra, não segurança


async def avaliar(
    enviar: Enviar,
    ativas: Ativas,
    n: int = 50,
    lead: str = "roteiro",
    concorrencia: int = 8,
    semente: int | None = None,
    pausa_s: float = 0.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sem = asyncio.Semaphore(concorrencia)

    async def um(caso):
        p = Persona.from_gold(caso)
        ld = LeadFastAgent(p) if lead == "fastagent" else LeadRoteiro(p)
        async with sem:
            try:
                return await conversar(p, ld, enviar, ativas, pausa_s=pausa_s)
            except RuntimeError as e:  # LLM do lead fora (cota, rede): a conversa não conta na métrica
                return {"persona": p, "erro_lead": str(e)[:200]}
            finally:
                if isinstance(ld, LeadFastAgent):
                    await ld.fechar()

    todos = await asyncio.gather(*[um(c) for c in carregar_gold(n, semente)])
    validos = [r for r in todos if "erro_lead" not in r]
    m = metricas(validos)
    m["conversas_com_erro_do_lead"] = len(todos) - len(validos)
    return m, validos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="agente no ar (ex.: http://localhost:8080)")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--lead", choices=["roteiro", "fastagent"], default="roteiro")
    ap.add_argument("--saida", default=str(ROOT / "docs" / "avaliacao.json"))
    ap.add_argument("--concorrencia", type=int, default=8, help="conversas em paralelo (Groq grátis: 1 ou 2)")
    ap.add_argument(
        "--aleatorio", type=int, metavar="SEMENTE", help="amostra aleatória da Gold (reprodutível)"
    )
    ap.add_argument("--pausa", type=float, default=0.0, help="segundos entre as mensagens do lead")
    ap.add_argument("--channel-key", default=os.environ.get("CHANNEL_API_KEY"), help="x-channel-key")
    a = ap.parse_args()
    headers = {"x-channel-key": a.channel_key} if a.channel_key else {}

    async def run():
        async with httpx.AsyncClient(base_url=a.url, timeout=60, headers=headers) as c:

            async def enviar(cid, texto):
                return (await c.post("/v1/messages", json={"conversation_id": cid, "text": texto})).json()

            async def ativas(cid):
                return (await c.get(f"/v1/conversations/{cid}/outbox")).json()

            return await avaliar(enviar, ativas, a.n, a.lead, a.concorrencia, a.aleatorio, a.pausa)

    m, res = asyncio.run(run())
    salvar(Path(a.saida), m, res)
    print(json.dumps(m, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
