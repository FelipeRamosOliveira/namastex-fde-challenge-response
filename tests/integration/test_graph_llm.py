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


async def test_oi_inicial_nao_ganha_frase_do_redator(stable_quote_url, tmp_path):
    fake = FakeLLM(redigir=lambda t: "Tudo bem? Como posso ajudar?")
    llm = LLMClient([GROQ], MemoryStore(), fake.http())
    s = Settings(_env_file=None, quote_api_url=stable_quote_url, checkpoint_db=str(tmp_path / "ck.sqlite"))
    async with AutoSeguroAgent(s, llm=llm) as ag:
        r = await ag.handle("L2", "oi")
    assert r["reply"].startswith("Oi! Aqui é o assistente")


async def test_texto_livre_ganha_frase_e_confirmacao_do_que_foi_anotado(stable_quote_url, tmp_path):
    """Teste de deploy externo (30/09/2026): com Groq ligado, dados fora de ordem recebiam a
    mesma pergunta 5 vezes, sem frase do redator: igual ao modo sem LLM."""

    def extrai(t: str) -> dict:
        t = t.lower()
        if "[cep_" in t:
            return {"cep_token": t[t.index("[cep_") : t.index("]", t.index("[cep_")) + 1].upper()}
        if "plano do meio" in t:
            return {"plano_id": "completo"}
        return {}

    def redige(t: str) -> str:
        if "plano do meio" in t:
            return ""  # LLM sem frase: a confirmação determinística aparece
        if "pode cotar" in t:
            return "Claro, vamos cotar agora!"  # anuncia passo que não acontece: descartada
        return "Perfeito, anotado!"

    fake = FakeLLM(extrair=extrai, redigir=redige)
    llm = LLMClient([GROQ], MemoryStore(), fake.http())
    s = Settings(_env_file=None, quote_api_url=stable_quote_url, checkpoint_db=str(tmp_path / "ck.sqlite"))
    async with AutoSeguroAgent(s, llm=llm, hoje=lambda: date(2026, 9, 30)) as ag:
        r1 = await ag.handle("L3", "boa tarde! comprei um hb20 ano passado, quanto fica o seguro?")
        r2 = await ag.handle("L3", "moro na paulista, cep 01310-100")
        r3 = await ag.handle("L3", "quero o plano do meio, nao preciso de carro reserva")
        r4 = await ag.handle("L3", "isso mesmo, pode cotar")
        r5 = await ag.handle("L3", "é do ano passado")
        r6 = await ag.handle("L3", "32")  # resposta curta e direta: sem frase

    # 1º turno: saudação, frase e só o ano (o modelo o lead já disse)
    assert r1["reply"] == (
        "Oi! Aqui é o assistente da AutoSeguro. Vou te ajudar a cotar o seguro do seu carro.\n"
        "Perfeito, anotado!\nE qual é o ano do carro? (ex.: 2021)"
    )
    # com frase do LLM, o "Anotei" determinístico sai (nada de confirmar duas vezes)
    assert r2["reply"] == (
        "Perfeito, anotado!\nPra fazer a cotação, ainda preciso saber o ano do carro (ex.: 2021)."
    )
    # sem frase, a confirmação determinística fica
    assert r3["reply"].startswith("Anotei o plano Completo. Pra fazer a cotação, ainda preciso saber o ano")
    assert "vamos cotar" not in r4["reply"] and r4["reply"].startswith("Pra fazer a cotação")
    assert r5["stage"] == "coletando" and "idade" in r5["reply"]
    assert not r6["reply"].startswith("Perfeito")
