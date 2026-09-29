"""Canal Omni: webhook do provider (round-trip) e envio ativo por /api/v2/messages/send.

O Omni falso segue o contrato lido do código do Omni (webhook-provider.ts / types.ts):
o payload de entrada é o mesmo `WebhookPayload` e o envio usa `instanceId`, `to`, `text` + x-api-key.
"""

import asyncio
import uuid
from datetime import date

import httpx
import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from autoseguro.agent.templates import brl
from autoseguro.config import get_settings

pytestmark = pytest.mark.integration

INSTANCE = str(uuid.uuid4())
CHAT = "5511999998888@s.whatsapp.net"
BEARER = {"Authorization": "Bearer chave-do-provider"}


def fake_omni():
    enviados: list[dict] = []
    omni = FastAPI()

    @omni.post("/api/v2/messages/send")
    async def send(req: Request, x_api_key: str = Header(default="")):
        body = await req.json()
        enviados.append({**body, "_key": x_api_key})
        return {"success": True}

    return omni, enviados


def payload(texto: str | None, chat: str = CHAT) -> dict:
    """Formato exato do WebhookPayload do Omni."""
    return {
        "event": {"id": str(uuid.uuid4()), "type": "message.received", "timestamp": 1790000000000},
        "instance": {"id": INSTANCE, "channelType": "whatsapp-baileys"},
        "chat": {"id": chat},
        "sender": {"id": chat, "name": "Ana Souza", "personId": str(uuid.uuid4())},
        "content": {"text": texto} if texto is not None else {},
        "traceId": str(uuid.uuid4()),
        "replyEndpoint": "POST /api/v2/messages/send",
    }


class Interruptor(httpx.AsyncBaseTransport):
    def __init__(self):
        self.fora = False
        self.real = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        if self.fora and request.url.path == "/quote":
            return httpx.Response(503, json={"error": "upstream_unavailable"})
        return await self.real.handle_async_request(request)


@pytest.fixture
def ambiente(stable_quote_url, tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_API_URL", stable_quote_url)
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "omni.sqlite"))
    monkeypatch.setenv("TRACE_API_KEY", "op")
    monkeypatch.setenv("OMNI_PROVIDER_KEY", "chave-do-provider")
    monkeypatch.setenv("OMNI_URL", "http://omni")
    monkeypatch.setenv("OMNI_API_KEY", "chave-da-api-omni")
    monkeypatch.setenv("QUOTE_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("RETRY_FUNDO_DELAYS_S", "[0.3, 0.3]")
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    from autoseguro.api.app import app

    omni, enviados = fake_omni()
    chave = Interruptor()
    with TestClient(app) as c:
        ag = app.state.agent
        ag.omni.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=omni), base_url="http://omni")
        http = httpx.AsyncClient(base_url=stable_quote_url, transport=chave)
        ag.services.quote.http = http
        ag.services.planos.http = http
        yield c, enviados, chave, ag
    get_settings.cache_clear()


def falar(c, texto, chat=CHAT):
    r = c.post("/omni/webhook", json=payload(texto, chat), headers=BEARER)
    assert r.status_code == 200, r.text
    return r.json()


def test_webhook_exige_bearer_do_provider(ambiente):
    c, *_ = ambiente
    assert c.post("/omni/webhook", json=payload("oi")).status_code == 401
    assert (
        c.post("/omni/webhook", json=payload("oi"), headers={"Authorization": "Bearer x"}).status_code == 401
    )


def test_conversa_pelo_omni_e_cotacao_em_segundo_plano_volta_pelo_omni(ambiente):
    c, enviados, chave, ag = ambiente
    assert "ano do seu carro" in falar(c, "oi, quero cotar")["reply"]
    for t in ["é um Corolla 2020", "tenho 35 anos", "cep 01310-100", "completo", "hoje"]:
        falar(c, t)
    chave.fora = True
    r = falar(c, "sim")
    assert "tentando de novo" in r["reply"] and "R$" not in r["reply"]
    chave.fora = False
    for _ in range(40):
        if enviados:
            break
        asyncio.run(asyncio.sleep(0.1))
    assert enviados, "cotação em segundo plano não foi enviada pelo Omni"
    msg = enviados[-1]
    assert msg["instanceId"] == INSTANCE and msg["to"] == CHAT and msg["_key"] == "chave-da-api-omni"
    direto = httpx.post(
        str(ag.s.quote_api_url) + "/quote",
        json={
            "plano_id": "completo",
            "idade": 35,
            "veiculo_ano": 2020,
            "cep": "01310-100",
            "data_inicio": date.today().isoformat(),
        },
    ).json()
    assert msg["text"].startswith("Consegui!") and brl(direto["premio_mensal"]) in msg["text"]


def test_vendedor_responde_pelo_omni(ambiente):
    c, enviados, *_ = ambiente
    falar(c, "oi")
    assert "atendente" in falar(c, "quero falar com um atendente")["reply"]
    conv = f"omni:{INSTANCE}:{CHAT}"
    r = c.post(
        f"/v1/conversations/{conv}/operador",
        headers={"x-api-key": "op"},
        json={"acao": "responder", "texto": "Oi, aqui é o Marcos!"},
    )
    assert r.status_code == 200
    assert enviados[-1]["text"] == "Oi, aqui é o Marcos!" and enviados[-1]["to"] == CHAT


def test_reentrega_do_mesmo_evento_nao_duplica(ambiente):
    c, *_ = ambiente
    p = payload("oi")
    a = c.post("/omni/webhook", json=p, headers=BEARER).json()
    b = c.post("/omni/webhook", json=p, headers=BEARER).json()
    assert a == b
    t = c.get(f"/v1/conversations/omni:{INSTANCE}:{CHAT}/trace", headers={"x-api-key": "op"}).json()
    assert len([m for m in t["transcript"] if m["role"] == "lead"]) == 1


def test_mensagem_sem_texto_pede_para_escrever(ambiente):
    c, *_ = ambiente
    falar(c, "oi")
    assert "por escrito" in falar(c, None)["reply"]


def test_nome_do_remetente_do_omni_nao_e_guardado(ambiente):
    c, *_ = ambiente
    falar(c, "oi, quero cotar")
    t = c.get(f"/v1/conversations/omni:{INSTANCE}:{CHAT}/trace", headers={"x-api-key": "op"}).json()
    assert "Ana" not in str(t) and CHAT not in str(t)
