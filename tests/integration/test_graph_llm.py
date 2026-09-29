"""Grafo com LLM (Groq falso) + quote-api ORIGINAL: o LLM ajuda a entender, nunca decide preço."""

from datetime import date

import httpx
import pytest
from fake_llm import FakeLLM

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.agent.templates import brl
from autoseguro.config import Settings
from autoseguro.llm.client import LLMClient, Provider
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration
GROQ = Provider("groq", "https://api.groq.com/openai/v1", "gsk_teste", "openai/gpt-oss-20b", True)


def entende(t: str) -> dict:
    """LLM falso que entende as frases livres usadas no teste."""
    t = t.lower()
    if "onix vinte e um" in t or "onix 21" in t:
        return {"veiculo_ano": 2021}
    if "trinta e dois" in t or "32" in t:
        return {"idade": 32}
    if "[cep_" in t:
        return {"cep_token": t[t.index("[cep_") : t.index("]", t.index("[cep_")) + 1].upper()}
    if "top" in t:
        return {"plano_id": "premium"}
    if "semana que vem" in t:
        return {"data_inicio": "2026-10-06"}
    if t.startswith("isso") or "pode cotar" in t:
        return {"intents": ["aceite"]}
    return {}


def redige(t: str) -> str:
    if "franquia" in t.lower():
        return "Boa pergunta! A franquia é a parte que você paga se acionar o seguro."
    if "barato" in t.lower():
        return "Sai só R$ 10,00 por mês!"  # o redator vai descartar
    return ""


async def test_conversa_livre_com_llm_e_valor_da_api(stable_quote_url, tmp_path):
    fake = FakeLLM(extrair=entende, redigir=redige)
    llm = LLMClient([GROQ], MemoryStore(), fake.http())
    s = Settings(_env_file=None, quote_api_url=stable_quote_url, checkpoint_db=str(tmp_path / "ck.sqlite"))
    hoje = date(2026, 9, 29)
    async with AutoSeguroAgent(s, llm=llm, hoje=lambda: hoje) as ag:
        await ag.handle("L1", "oi! me chamo Ana Souza, cpf 389.083.863-43")
        await ag.handle("L1", "é um onix 21")
        r = await ag.handle("L1", "o que é franquia? tenho 32 anos")
        assert r["reply"].startswith("Boa pergunta!")  # ponte do redator
        await ag.handle("L1", "o carro dorme no 01310-100")
        r = await ag.handle("L1", "quero o top, o mais barato não serve")
        assert "R$ 10,00" not in r["reply"]  # preço inventado pelo redator descartado
        await ag.handle("L1", "semana que vem")
        r = await ag.handle("L1", "isso, pode cotar")
        t = await ag.trace("L1")

    assert r["stage"] == "cotado"
    direto = httpx.post(
        stable_quote_url + "/quote",
        json={
            "plano_id": "premium",
            "idade": 32,
            "veiculo_ano": 2021,
            "cep": "01310-100",
            "data_inicio": "2026-10-06",
        },
    ).json()
    assert brl(direto["premio_mensal"]) in r["reply"]

    enviado = fake.prompts()
    for dado in ("Ana", "Souza", "389.083.863-43", "01310-100"):
        assert dado not in enviado
    fontes = {e["fonte"] for e in t["events"] if e["type"] == "extracao"}
    assert any(f.startswith("llm:groq") for f in fontes)
    assert any(e["type"] == "redator" and e["usada"] for e in t["events"])
