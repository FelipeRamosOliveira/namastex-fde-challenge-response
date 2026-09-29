"""API FastAPI com o ciclo de vida real (lifespan) e a quote-api original."""

import pytest
from fastapi.testclient import TestClient

from autoseguro.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def client(stable_quote_url, tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_API_URL", stable_quote_url)
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "api.sqlite"))
    monkeypatch.setenv("TRACE_API_KEY", "trace-secreta")
    monkeypatch.setenv("CHANNEL_API_KEY", "canal-secreto")
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # não lê o .env do repo
    get_settings.cache_clear()
    from autoseguro.api.app import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


CANAL = {"x-channel-key": "canal-secreto"}


def test_mensagem_exige_chave_do_canal(client):
    r = client.post("/v1/messages", json={"conversation_id": "a1", "text": "oi"})
    assert r.status_code == 401
    r = client.post("/v1/messages", json={"conversation_id": "a1", "text": "oi"}, headers=CANAL)
    assert r.status_code == 200 and "ano do seu carro" in r.json()["reply"]


def test_trace_exige_chave_e_nao_expoe_pii(client):
    client.post(
        "/v1/messages",
        json={"conversation_id": "a2", "text": "oi, cpf 389.083.863-43, email x.y@z.com"},
        headers=CANAL,
    )
    assert client.get("/v1/conversations/a2/trace").status_code == 401
    assert client.get("/v1/conversations/a2/trace", headers={"x-api-key": "errada"}).status_code == 401
    r = client.get("/v1/conversations/a2/trace", headers={"x-api-key": "trace-secreta"})
    assert r.status_code == 200
    assert "389.083.863-43" not in r.text and "x.y@z.com" not in r.text and "vault" not in r.text


def test_limites_de_entrada(client):
    grande = {"conversation_id": "a3", "text": "x" * 4001}
    assert client.post("/v1/messages", json=grande, headers=CANAL).status_code == 422
    mid = {"conversation_id": "a3", "text": "oi", "message_id": "m" * 101}
    assert client.post("/v1/messages", json=mid, headers=CANAL).status_code == 422
