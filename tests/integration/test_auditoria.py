"""Regressão dos achados da auditoria independente pós-V1 (um bloco por tema)."""

import asyncio
import logging
import time

import httpx
import pytest
from test_etapa5 import FELIZ, esperar, montar

from autoseguro.agent.outbox import REENTREGA_KEY, Outbox
from autoseguro.agent.service import PENDENTES_KEY, AutoSeguroAgent
from autoseguro.tools.handoff import HandoffQueue
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration


def _mesmo_store(services, store):
    services.store = store
    services.quote.store = store
    services.handoff.store = store
    return services


# ---------------------------------------------------------------- segundo plano
async def test_redis_perdido_tentativa_reconstruida_do_checkpoint(stable_quote_url, tmp_path):
    """O Redis reiniciou sem as tentativas: na subida, o checkpoint (SQLite) reconstrói."""
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.5])
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("a1", m)
        chave.fora = True
        assert (await ag.handle("a1", "sim"))["stage"] == "aguardando_cotacao"
    chave.fora = False
    s2, services2, _ = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.5])  # store novo e vazio
    async with AutoSeguroAgent(s2, services=services2) as ag2:
        t = await esperar(ag2, "a1", lambda t: t["stage"] == "cotado", n=60)
    assert t["stage"] == "cotado"


async def test_mensagem_do_lead_reconstroi_tentativa_perdida(stable_quote_url, tmp_path):
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.5])
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("a2", m)
        chave.fora = True
        r = await ag.handle("a2", "sim")
        await ag.store.hdel(PENDENTES_KEY, r["conversation_ref"])  # Redis perdeu a entrada
        chave.fora = False
        r2 = await ag.handle("a2", "e aí, saiu?")
        assert "Ainda estou tentando" in r2["reply"]
        t = await esperar(ag, "a2", lambda t: t["stage"] == "cotado", n=60)
    assert t["stage"] == "cotado"


# ---------------------------------------------------------------- entrega ativa
class OmniFalho:
    def __init__(self, falhas: int) -> None:
        self.falhas, self.envios = falhas, 0

    async def enviar(self, ref, texto):
        self.envios += 1
        if self.envios <= self.falhas:
            raise httpx.ConnectError("omni fora")
        return {"status": 200}


async def test_entrega_que_falhou_e_reentregue_e_registrada(caplog):
    store, omni = MemoryStore(), OmniFalho(falhas=1)
    ob = Outbox(store, omni=omni)
    with caplog.at_level(logging.INFO, logger="autoseguro.trace"):
        item = await ob.push("conv_x", "Consegui! Cotação pronta.", "agente")
        assert not item["entregue_omni"]
        assert "entrega_falhou" in caplog.text and "Consegui" not in caplog.text  # evento sem o texto
        assert await ob.reentregar(lambda ref: None) == 0  # ainda não venceu o backoff
        assert await ob.reentregar(lambda ref: None, agora=time.time() + 11) == 1
    assert await store.hgetall(REENTREGA_KEY) == {}
    assert omni.envios == 2 and "entrega_reentregue" in caplog.text


async def test_entrega_desiste_depois_das_tentativas(caplog):
    store = MemoryStore()

    def recusa(request):
        return httpx.Response(503)

    async def canal(ref):
        return "5521999998888"

    ob = Outbox(store, "http://canal/webhook", http=httpx.AsyncClient(transport=httpx.MockTransport(recusa)))
    with caplog.at_level(logging.INFO, logger="autoseguro.trace"):
        await ob.push("conv_y", "Oi de novo!", "agente")
        agora = time.time()
        for _ in range(6):
            agora += 1000
            await ob.reentregar(canal, agora=agora)
    assert await store.hgetall(REENTREGA_KEY) == {}
    assert "entrega_desistiu" in caplog.text and "5521999998888" not in caplog.text
    assert len(await ob.listar("conv_y")) == 1  # continua no outbox para o canal buscar


async def test_sem_destino_configurado_nao_agenda_reentrega():
    store = MemoryStore()
    await Outbox(store).push("conv_z", "texto", "agente")
    assert await store.hgetall(REENTREGA_KEY) == {}


# ---------------------------------------------------------------- idempotência
async def test_reentrega_do_webhook_depois_de_reinicio_nao_reprocessa(stable_quote_url, tmp_path):
    store = MemoryStore()
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=_mesmo_store(services, store)) as ag:
        await ag.handle("omni:i:5521999", "oi", message_id="omni_evt1")
        r1 = await ag.handle("omni:i:5521999", "é um Corolla 2020", message_id="omni_evt2")
        n = len((await ag.trace("omni:i:5521999"))["transcript"])
    s2, services2, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s2, services=_mesmo_store(services2, store)) as ag2:  # processo novo
        r2 = await ag2.handle("omni:i:5521999", "é um Corolla 2020", message_id="omni_evt2")
        t = await ag2.trace("omni:i:5521999")
    assert r2["duplicada"] and r2["reply"] == r1["reply"] and r2["conversation_id"] == "omni:i:5521999"
    assert len(t["transcript"]) == n
    salvos = [v for k, (v, _) in store._d.items() if k.startswith("dedup:")]
    assert salvos and all("5521999" not in str(v) for v in salvos)  # sem o id do canal no Redis


# ---------------------------------------------------------------- handoff
class FilaFora(HandoffQueue):
    async def registrar(self, *a, **kw):
        raise ConnectionError("redis fora")


async def test_registro_do_handoff_que_falhou_e_concluido_em_segundo_plano(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    services.handoff = FilaFora(services.store)  # a ferramenta MCP falha em todas as tentativas
    async with AutoSeguroAgent(s, services=services) as ag:
        r = await ag.handle("h1", "quero falar com um atendente")
        assert r["stage"] == "handoff" and r["handoff"]["status"].startswith("falha_registro")
        hid = r["handoff"]["handoff_id"]
        assert hid  # id nasce antes do registro
        t = await esperar(ag, "h1", lambda t: t["handoff"]["status"] == "pendente", n=40)
        fila = await ag.handoffs.listar()
    assert [i["handoff_id"] for i in fila] == [hid]
    assert any(e["type"] == "handoff_registrado" for e in t["events"])
    assert t["pausado_com_humano"]


async def test_registro_com_mesmo_id_nao_duplica():
    fila = HandoffQueue(MemoryStore())
    a = await fila.registrar("conv_1", "pedido_humano", "resumo", handoff_id="ho_abc")
    b = await fila.registrar("conv_1", "pedido_humano", "resumo", handoff_id="ho_abc")
    assert a["handoff_id"] == b["handoff_id"] == "ho_abc" and len(await fila.listar()) == 1


async def test_ciclo_de_vida_na_fila(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=services) as ag:
        r = await ag.handle("h2", "quero falar com um atendente")
        ref = r["conversation_ref"]
        assert [i["status"] for i in await ag.handoffs.listar()] == ["pendente"]
        await ag.operador(ref, "responder", "Oi! Sou o Marcos, vou te ajudar.")
        assert [i["status"] for i in await ag.handoffs.listar()] == ["em_atendimento"]
        await ag.operador(ref, "devolver")
        assert [i["status"] for i in await ag.handoffs.listar()] == ["devolvido"]
        assert await ag.handoffs.listar("pendente") == []
        await ag.handle("h2", "quero falar com uma pessoa de verdade")
        await ag.operador(ref, "encerrar")
        assert sorted(i["status"] for i in await ag.handoffs.listar()) == ["devolvido", "encerrado"]


async def test_trocar_para_asyncio_nao_deixa_tarefa_pendurada(stable_quote_url, tmp_path):
    """O laço de reentrega é cancelado junto com o agente (sem tarefa órfã no encerramento)."""
    s, services, _ = montar(stable_quote_url, tmp_path, reentrega_intervalo_s=0.05)
    async with AutoSeguroAgent(s, services=services) as ag:
        await asyncio.sleep(0.2)
        assert ag._tasks
    assert all(t.done() for t in ag._tasks) or not ag._tasks
