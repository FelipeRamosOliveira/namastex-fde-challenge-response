"""Grafo LangGraph de ponta a ponta com MCP em processo e a quote-api ORIGINAL."""

from datetime import date

import httpx
import pytest

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.agent.templates import brl
from autoseguro.config import Settings
from autoseguro.tools.mcp_server import Services
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration

CPF = "389.083.863-43"


def cfg(url, tmp_path, **kw):
    return Settings(_env_file=None, quote_api_url=url, checkpoint_db=str(tmp_path / "ck.sqlite"), **kw)


async def conversa(agent, cid, msgs):
    outs = []
    for m in msgs:
        outs.append(await agent.handle(cid, m))
    return outs


FELIZ = [
    "Oi, quero fazer um seguro",
    "é um Corolla 2020",
    "tenho 35 anos",
    "cep 01310-100",
    "completo",
    "hoje",
]


async def test_caminho_feliz_valor_igual_api(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        outs = await conversa(ag, "c1", FELIZ)
        assert outs[-1]["stage"] == "confirmando"
        assert "Está certo?" in outs[-1]["reply"]
        cot = await ag.handle("c1", "sim")
        assert cot["stage"] == "cotado" and cot["quote_id"]
        direto = httpx.post(
            stable_quote_url + "/quote",
            json={
                "plano_id": "completo",
                "idade": 35,
                "veiculo_ano": 2020,
                "cep": "01310-100",
                "data_inicio": date.today().isoformat(),
            },
        ).json()
        assert brl(direto["premio_mensal"]) in cot["reply"]
        assert brl(direto["franquia"]) in cot["reply"]
        fim = await ag.handle("c1", "fechado!")
        assert fim["stage"] == "handoff" and fim["handoff"]["motivo"] == "pronto_para_fechar"
        pos = await ag.handle("c1", "e aí?")
        assert "equipe" in pos["reply"]


async def test_nao_confunde_data_nem_idade_do_carro(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await ag.handle("c2", "oi")
        await ag.handle("c2", "quero começar em 2030-10-15")
        r = await ag.handle("c2", "meu carro tem 12 anos, é um onix")
        t = await ag.trace("c2")
        assert "veiculo_ano" not in t["slots"] and "idade" not in t["slots"]
        assert "ano" in r["reply"]


async def test_recusa_por_idade_sem_chamar_quote(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c3", ["oi", "Gol 2021"])
        r = await ag.handle("c3", "tenho 80 anos")
        assert r["stage"] == "handoff" and r["handoff"]["motivo"] == "recusa_regra"
        assert "75" in r["reply"]
        t = await ag.trace("c3")
        assert not [e for e in t["events"] if e["type"] == "cotacao"]


async def test_correcao_na_confirmacao(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c4", FELIZ)
        r = await ag.handle("c4", "não")
        assert "errado" in r["reply"]
        r = await ag.handle("c4", "na verdade tenho 40 anos")
        assert r["stage"] == "confirmando" and "Idade 40" in r["reply"]


async def test_retomada_apos_reiniciar(stable_quote_url, tmp_path):
    s = cfg(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s) as ag:
        await conversa(ag, "c5", FELIZ[:4])
    async with AutoSeguroAgent(s) as ag2:  # novo processo, mesmo checkpoint
        r = await ag2.handle("c5", "premium")
        assert "A partir de quando" in r["reply"]
        t = await ag2.trace("c5")
        assert t["slots"]["idade"] == 35 and t["slots"]["plano_id"] == "premium"


async def test_api_fora_vai_para_humano_sem_preco(quote_api, tmp_path):
    with quote_api(failure=1.0) as url:
        async with AutoSeguroAgent(cfg(url, tmp_path, quote_max_attempts=2)) as ag:
            await conversa(ag, "c6", FELIZ)
            r = await ag.handle("c6", "sim")
    assert r["stage"] == "handoff" and r["handoff"]["motivo"] == "cotacao_indisponivel"
    assert "R$" not in r["reply"]


async def test_pii_nunca_sai_do_vault(stable_quote_url, tmp_path):
    store = MemoryStore()
    s = cfg(stable_quote_url, tmp_path)
    services = Services.from_settings(s, store=store)
    async with AutoSeguroAgent(s, services=services) as ag:
        await ag.handle("c7", f"oi, meu cpf é {CPF} e email ana.silva@gmail.com, whats 21 97224-2584")
        await ag.handle("c7", "quero falar com um atendente")
        t = await ag.trace("c7")
        fila = await services.handoff.listar()
    blob = str(t) + str(fila)
    for sensivel in (CPF, "38908386343", "ana.silva@gmail.com", "97224-2584"):
        assert sensivel not in blob
    assert "[CPF_1]" in blob and fila[0]["motivo"] == "pedido_humano"


async def test_midia_duas_vezes_vai_para_humano(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await ag.handle("c8", "oi")
        r1 = await ag.handle("c8", "[audio] mensagem de voz (18s)")
        assert "por escrito" in r1["reply"] and r1["stage"] != "handoff"
        r2 = await ag.handle("c8", "[documento] CNH_frente.pdf")
        assert r2["handoff"]["motivo"] == "midia"


async def test_objecao_oferece_essencial_real_depois_humano(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c9", [*FELIZ[:4], "premium", "hoje", "sim"])
        r = await ag.handle("c9", "achei caro")
        direto = httpx.post(
            stable_quote_url + "/quote",
            json={
                "plano_id": "essencial",
                "idade": 35,
                "veiculo_ano": 2020,
                "cep": "01310-100",
                "data_inicio": date.today().isoformat(),
            },
        ).json()
        assert "Essencial" in r["reply"] and brl(direto["premio_mensal"]) in r["reply"]
        r = await ag.handle("c9", "ainda ta caro, a porto seguro me ofereceu menos")
        assert r["handoff"]["motivo"] == "objecao_preco"


async def test_trace_tem_ids_e_tentativas(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c10", [*FELIZ, "sim"])
        t = await ag.trace("c10")
    tipos = [e["type"] for e in t["events"]]
    assert {"message_in", "extracao", "pre_validacao", "cotacao", "message_out"} <= set(tipos)
    cot = next(e for e in t["events"] if e["type"] == "cotacao")
    assert cot["quote_request_id"].startswith("qr_") and cot["attempts"]
    assert all(e["event_id"] and e["conversation_id"] == "c10" for e in t["events"])
