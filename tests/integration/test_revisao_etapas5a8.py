"""Regressão dos achados da revisão independente das etapas 5 a 8 (um teste por achado)."""

import asyncio
from datetime import date

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_etapa5 import FELIZ, esperar, montar

from autoseguro.agent.service import PENDENTES_KEY, AutoSeguroAgent
from autoseguro.agent.templates import brl
from autoseguro.config import Settings, get_settings
from autoseguro.guardrails.pii import PiiVault, configurar_chave_vault, mask
from autoseguro.sim.avaliar import conversar, metricas
from autoseguro.sim.leads import Persona
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration


def cotacao_direta(url, plano):
    return httpx.post(
        url + "/quote",
        json={
            "plano_id": plano,
            "idade": 35,
            "veiculo_ano": 2020,
            "cep": "01310-100",
            "data_inicio": date.today().isoformat(),
        },
    ).json()


# ---------------------------------------------------------------- 1. canal aberto
@pytest.fixture
def api(stable_quote_url, tmp_path, monkeypatch):
    def subir(**env):
        monkeypatch.setenv("QUOTE_API_URL", stable_quote_url)
        monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "api.sqlite"))
        monkeypatch.setenv("TRACE_API_KEY", "op")
        monkeypatch.delenv("MCP_URL", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.chdir(tmp_path)
        get_settings.cache_clear()
        from autoseguro.api.app import app

        return TestClient(app)

    yield subir
    get_settings.cache_clear()


def test_1_id_do_omni_nao_entra_pelo_canal_generico(api):
    with api() as c:
        body = {"conversation_id": "omni:inst:5511999998888@s.whatsapp.net", "text": "sim"}
        assert c.post("/v1/messages", json=body).status_code == 403
        assert c.get("/v1/conversations/omni:inst:5511999998888@s.whatsapp.net/outbox").status_code == 403


def test_1_docker_nao_sobe_sem_segredos(api):
    with pytest.raises(RuntimeError, match="CHANNEL_API_KEY"), api(EXIGIR_SEGREDOS="true"):
        pass


# ---------------------------------------------------------------- 2. correção durante a espera
async def test_2_lead_corrige_plano_enquanto_espera_e_nao_recebe_cotacao_antiga(stable_quote_url, tmp_path):
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.3, 0.3, 0.3])
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("r2", m)
        chave.fora = True
        assert (await ag.handle("r2", "sim"))["stage"] == "aguardando_cotacao"
        r = await ag.handle("r2", "na verdade quero o premium")
        assert r["stage"] == "confirmando" and "Premium" in r["reply"]
        chave.fora = False
        await asyncio.sleep(1.0)  # a tentativa pendente acorda e desiste
        assert await ag.mensagens_ativas("r2") == []
        assert await services.store.hgetall(PENDENTES_KEY) == {}
        r = await ag.handle("r2", "sim")
    assert r["stage"] == "cotado"
    assert brl(cotacao_direta(stable_quote_url, "premium")["premio_mensal"]) in r["reply"]


# ---------------------------------------------------------------- 3. texto do operador
async def test_3_operador_passa_pelo_guardrail_e_outbox_sem_id_do_canal(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    cid = "5511987654321"
    async with AutoSeguroAgent(s, services=services) as ag:
        await ag.handle(cid, "oi, me chamo Ana Souza")
        await ag.handle(cid, "quero falar com um atendente")
        for ruim in (
            "Fica R$ 12,34 por mês",
            "Seu CPF 389.083.863-43 confere?",
            "Oi Ana, tudo certo?",
        ):
            with pytest.raises(ValueError, match="guardrail"):
                await ag.operador(cid, "responder", ruim)
        ok = await ag.operador(cid, "responder", "Oi! Sou o Marcos, já vi seu caso.")
        ativas = await ag.mensagens_ativas(cid)
    assert ok["ok"] and len(ativas) == 1
    assert cid not in str(ativas) and "conversation_id" not in ativas[0]


# ---------------------------------------------------------------- 4. chave do vault
def test_4_chave_trocada_nao_derruba_e_rotacao_abre():
    a, b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    try:
        configurar_chave_vault(a)
        v = PiiVault()
        tok = mask("cep 01310-100", v).text.split()[-1]
        configurar_chave_vault(b)
        assert v.reveal(tok) is None
        mask("meu cep é 04567-000", v)  # não levanta InvalidToken
        configurar_chave_vault(f"{b},{a}")
        assert v.reveal(tok) == "01310-100"
    finally:
        configurar_chave_vault(None)


async def test_4_cep_ilegivel_pede_o_cep_de_novo_sem_cotar(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path, vault_key=Fernet.generate_key().decode())
    try:
        async with AutoSeguroAgent(s, services=services) as ag:
            for m in FELIZ:
                await ag.handle("r4", m)
            configurar_chave_vault(Fernet.generate_key().decode())  # chave trocada
            r = await ag.handle("r4", "sim")
            assert r["stage"] == "coletando" and "CEP" in r["reply"] and "R$" not in r["reply"]
            r = await ag.handle("r4", "01310-100")
            r = await ag.handle("r4", "sim")
        assert r["stage"] == "cotado"
    finally:
        configurar_chave_vault(None)


# ---------------------------------------------------------------- 5. pendentes
async def test_5_pendentes_concorrentes_nao_se_perdem():
    st = MemoryStore()
    await asyncio.gather(*[st.hset(PENDENTES_KEY, f"conv_{i}", {"due": i}) for i in range(10)])
    assert len(await st.hgetall(PENDENTES_KEY)) == 10


async def test_5_duas_replicas_executam_a_tentativa_uma_vez(stable_quote_url, tmp_path):
    store = MemoryStore()
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.4, 0.4])
    services.store = services.quote.store = store
    async with AutoSeguroAgent(s, services=services) as ag:
        for m in FELIZ:
            await ag.handle("r5", m)
        chave.fora = True
        await ag.handle("r5", "sim")
    chave.fora = False
    s2, sv2, _ = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.4, 0.4])
    s3, sv3, _ = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.4, 0.4])
    for sv in (sv2, sv3):
        sv.store = sv.quote.store = store
    async with AutoSeguroAgent(s2, services=sv2) as r1, AutoSeguroAgent(s3, services=sv3) as r2:
        t = await esperar(r1, "r5", lambda t: t["stage"] == "cotado")
        await asyncio.sleep(0.5)
        t = await r2.trace("r5")
        ativas = await r1.mensagens_ativas("r5")
    assert t["stage"] == "cotado"
    assert sum(e["type"] == "evento_sistema" for e in t["events"]) == 1
    assert len(ativas) == 1


# ---------------------------------------------------------------- 6. operador pelo ref da fila
async def test_6_operador_age_com_o_ref_que_a_fila_mostra(stable_quote_url, tmp_path):
    s, services, _ = montar(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s, services=services) as ag:
        await ag.handle("omni:inst:5511987654321@s.whatsapp.net", "quero falar com um atendente")
        ref = (await ag.handoffs.listar())[0]["conversation_id"]
        assert ref.startswith("conv_")
        d = await ag.operador(ref, "devolver")
        assert await ag.trace(ref) is not None
    assert d["stage"] == "coletando"


# ---------------------------------------------------------------- 7. métricas
class LeadFixo:
    def __init__(self, msgs):
        self.msgs = list(msgs)

    async def abrir(self):
        return self.msgs.pop(0)

    async def responder(self, _bot):
        return self.msgs.pop(0) if self.msgs else None


async def test_7_handoff_por_mensagem_ativa_tem_motivo_e_fica_a_parte(stable_quote_url, tmp_path):
    s, services, chave = montar(stable_quote_url, tmp_path, retry_fundo_delays_s=[0.2, 0.2])
    p = Persona("c1", 35, 2020, "Corolla 2020", "01310-100", "completo", "ganho")
    async with AutoSeguroAgent(s, services=services) as ag:
        chave.fora = True
        r = await conversar(p, LeadFixo([*FELIZ, "sim"]), ag.handle, ag.mensagens_ativas, espera_ativa_s=5)
    assert r["estado_final"] == "handoff" and r["motivo_handoff"] == "cotacao_indisponivel"
    m = metricas([r])
    assert m["handoff_api_indisponivel"] == 1 and m["handoff_coerente"] == "0/0"


# ---------------------------------------------------------------- 8 e 9. API
def test_8_chave_com_acento_da_401(api):
    with api() as c:
        assert c.get("/v1/handoffs", headers=[(b"x-api-key", "café".encode("latin-1"))]).status_code == 401


def test_9_reacao_do_omni_nao_vira_midia(api):
    with api(OMNI_PROVIDER_KEY="pk") as c:
        base = {
            "instance": {"id": "i1"},
            "chat": {"id": "5511999998888@s.whatsapp.net"},
            "content": {"emoji": "👍"},
        }
        h = {"Authorization": "Bearer pk"}
        for tipo in ("message.reaction", "message.received"):
            r = c.post("/omni/webhook", json={**base, "event": {"id": tipo, "type": tipo}}, headers=h)
            assert r.json() == {"parts": []}
        t = c.get("/v1/conversations/omni:i1:5511999998888@s.whatsapp.net/trace", headers={"x-api-key": "op"})
        assert t.status_code == 404  # nenhum turno foi criado


def test_settings_padrao_nao_exige_segredos():
    assert Settings(_env_file=None).exigir_segredos is False
