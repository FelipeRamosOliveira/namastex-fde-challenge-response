"""Conversa de demonstração com o LLM de verdade (Groq) e a quote-api.

Pré-requisitos: GROQ_API_KEY no .env e a quote-api no ar (docker compose up quote-api,
ou: cd vendor/challenge/quote-service && uv run uvicorn app.main:app --port 8000).
Uso: uv run python scripts/smoke_llm.py
"""

from __future__ import annotations

import asyncio
import tempfile

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.config import Settings

ROTEIRO = [
    "oi! vi o anúncio, quanto fica o seguro?",
    "é um onix 2021",
    "o que é franquia? ah, e tenho 32 anos",
    "o carro dorme no 01310-100",
    "quero o mais completo",
    "pode ser a partir de semana que vem",
    "isso, pode cotar",
    "achei caro",
    "fechado!",
]


async def main() -> None:
    s = Settings(checkpoint_db=tempfile.mktemp(suffix=".sqlite"))
    async with AutoSeguroAgent(s) as ag:
        if ag.llm:
            print("LLM ligado:", ", ".join(f"{p.name}/{p.model}" for p in ag.llm.providers), "\n")
        else:
            print("LLM desligado (sem GROQ_API_KEY): extração por regras\n")
        for msg in ROTEIRO:
            r = await ag.handle("smoke", msg)
            print(f"LEAD: {msg}\nAGENTE [{r['stage']}]: {r['reply']}\n")
            if r["stage"] == "handoff":
                break
        t = await ag.trace("smoke")
    fontes = [e.get("fonte") for e in t["events"] if e["type"] == "extracao"]
    print("fontes da extração:", fontes)


if __name__ == "__main__":
    asyncio.run(main())
