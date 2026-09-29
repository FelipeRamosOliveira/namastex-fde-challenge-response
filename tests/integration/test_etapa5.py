"""Etapa 5: cotação em segundo plano, retomada pelo checkpoint e humano no circuito (interrupt)."""

import asyncio
from datetime import date

import httpx
import pytest

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.agent.templates import brl
from autoseguro.config import Settings
from autoseguro.tools.mcp_server import Services
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration
FELIZ = ["oi", "é um Corolla 2020", "tenho 35 anos", "cep 01310-100", "completo", "hoje"]


class Interruptor(httpx.AsyncBaseTransport):
    """Encaminha para a quote-api original, mas devolve 503 enquanto `fora` for True."""

    def __init__(self, url: str) -> None:
        self.fora = False
        self.real = httpx.AsyncHTTPTransport()
        self.url = url

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.fora and request.url.path == "/quote":
            return httpx.Response(503, json={"error": "upstream_unavailable"})
        return await self.real.handle_async_request(request)


def montar(url, tmp_path, **kw):
    chave = Interruptor(url)
    s = Settings(
        _env_file=None,
        quote_api_url=url,
        checkpoint_db=str(tmp_path / "ck.sqlite"),
        quote_max_attempts=2,
        **kw,
    )
    http = httpx.AsyncClient(base_url=url, transport=chave)
    return s, Services.from_settings(s, store=MemoryStore(), http=http), chave


async def esperar(ag, cid, cond, n=60):
    for _ in range(n):
        await asyncio.sleep(0.1)
        t = await ag.trace(cid)
        if cond(t):
            return t
    return await ag.trace(cid)


async def test_api_volta_e_lead_recebe_a_cotacao_sem_humano(stable_quote_url, tmp_path):
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.3, 0.3, 0.3])
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("e1", m)
        chave.fora = True
        r = await ag.handle("e1", "sim")
        assert r["stage"] == "aguardando_cotacao"
        r2 = await ag.handle("e1", "e aí, saiu?")
        assert "Ainda estou tentando" in r2["reply"]
        chave.fora = False  # API voltou
        t = await esperar(ag, "e1", lambda t: t["stage"] == "cotado")
        for _ in range(20):
            ativas = await ag.mensagens_ativas("e1")
            if ativas:
                break
            await asyncio.sleep(0.1)
    assert t["stage"] == "cotado" and t["handoff"] is None
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
    assert ativas[-1]["texto"].startswith("Consegui!") and brl(direto["premio_mensal"]) in ativas[-1]["texto"]


async def test_tentativa_pendente_sobrevive_a_reinicio(stable_quote_url, tmp_path):
    store = MemoryStore()
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.5])
    services.store = store
    services.quote.store = store
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("e2", m)
        chave.fora = True
        await ag.handle("e2", "sim")
    # processo "caiu" antes da nova tentativa; sobe de novo com a API no ar
    chave.fora = False
    s2, services2, _ = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.5])
    services2.store = store
    services2.quote.store = store
    async with AutoSeguroAgent(s2, services=services2) as ag2:
        t = await esperar(ag2, "e2", lambda t: t["stage"] == "cotado")
    assert t["stage"] == "cotado"


async def test_humano_assume_responde_e_devolve_ao_bot(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ[:3]:
            await ag.handle("e3", m)
        r = await ag.handle("e3", "quero falar com um atendente")
        assert r["stage"] == "handoff"
        t = await ag.trace("e3")
        assert t["pausado_com_humano"] is True

        # lead escreve durante o atendimento humano: não acorda o bot, fica no histórico
        r = await ag.handle("e3", "oi? meu cpf é 389.083.863-43")
        assert "equipe" in r["reply"]
        t = await ag.trace("e3")
        assert t["pausado_com_humano"] is True and "[CPF_1]" in str(t["transcript"])
        assert "389.083.863-43" not in str(t)

        # operador responde e depois devolve ao bot
        await ag.operador("e3", "responder", "Oi! Sou o Marcos, já vi seu caso.")
        d = await ag.operador("e3", "devolver")
        assert d["stage"] == "coletando" and "devolveu" in d["entregue"]["texto"]
        ativas = await ag.mensagens_ativas("e3")
        assert [a["origem"] for a in ativas] == ["humano", "agente"]

        # bot retoma de onde parou (falta o CEP)
        r = await ag.handle("e3", "cep 01310-100")
        assert r["stage"] == "coletando" and "plano" in r["reply"].lower()
        fila = await ag.handoffs.listar()
    assert len(fila) == 1  # o handoff não foi registrado duas vezes na retomada


async def test_operador_encerra_e_conversa_recomeca(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=services) as ag:
        await ag.handle("e4", "oi")
        await ag.handle("e4", "quero falar com um atendente")
        d = await ag.operador("e4", "encerrar")
        assert d["stage"] == "encerrado"
        r = await ag.handle("e4", "oi de novo, quero cotar outro carro")
        assert r["stage"] == "coletando" and "ano do seu carro" in r["reply"]
        with pytest.raises(ValueError):
            await ag.operador("e4", "devolver")  # não está com humano


async def test_historico_de_checkpoints(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in [*FELIZ, "sim"]:
            await ag.handle("e5", m)
        h = await ag.historico("e5")
    nos = {n for p in h for n in p["executou"]}
    assert {"entrada", "decidir", "cotar", "saida"} <= nos
    assert h[-1]["stage"] == "cotado" and len(h) > 20
