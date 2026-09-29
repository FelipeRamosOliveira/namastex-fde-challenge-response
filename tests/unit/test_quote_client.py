"""Comportamento do cliente com transporte simulado (determinístico, sem rede)."""

import asyncio
import time

import httpx
import pytest

from autoseguro.config import Settings
from autoseguro.tools.quote_client import QuoteClient, QuoteStatus
from autoseguro.tools.store import MemoryStore

OK_BODY = {
    "plano_id": "completo",
    "plano_nome": "Completo",
    "premio_mensal": 209.9,
    "franquia": 3000,
    "coberturas": ["colisao"],
}
PAYLOAD = {"plano_id": "completo", "idade": 35, "veiculo_ano": 2022}


def make(handler, **overrides):
    cfg = dict(
        quote_api_url="http://q",
        quote_timeout_s=0.5,
        quote_hedge_after_s=0.2,
        quote_max_attempts=4,
        quote_backoff_base_s=0.01,
        quote_backoff_max_s=0.02,
    )
    s = Settings(_env_file=None, **{**cfg, **overrides})
    http = httpx.AsyncClient(base_url="http://q", transport=httpx.MockTransport(handler))
    return QuoteClient(s, MemoryStore(), http)


def sequence(*steps):
    """Cada passo: ('ok'|'500'|'422'|'400', atraso_s)."""
    calls = {"n": 0}

    async def handler(request):
        i = calls["n"]
        calls["n"] += 1
        kind, delay = steps[min(i, len(steps) - 1)]
        await asyncio.sleep(delay)
        if kind == "ok":
            return httpx.Response(200, json=OK_BODY)
        if kind == "422":
            return httpx.Response(422, json={"error": "cotacao_recusada", "motivo": "Idade acima do limite"})
        if kind == "400":
            return httpx.Response(400, json={"error": "payload_invalido", "detalhe": "x"})
        return httpx.Response(int(kind), json={"error": "upstream_unavailable"})

    return handler, calls


async def test_retry_em_5xx_ate_sucesso():
    h, calls = sequence(("503", 0), ("502", 0), ("ok", 0))
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.OK and out.quote == OK_BODY
    assert [a.outcome for a in out.attempts] == ["erro_5xx", "erro_5xx", "ok"]
    assert calls["n"] == 3


async def test_esgota_tentativas_sem_preco():
    h, calls = sequence(("500", 0))
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.INDISPONIVEL
    assert out.quote is None and out.quote_id is None
    assert calls["n"] == 4


async def test_422_nao_repete():
    h, calls = sequence(("422", 0))
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.RECUSADA and "limite" in out.motivo
    assert calls["n"] == 1


async def test_400_nao_repete():
    h, calls = sequence(("400", 0))
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.INVALIDA and calls["n"] == 1


async def test_hedging_vence_chamada_lenta():
    # 1a chamada demoraria 5 s; a 2a (hedge em 0,2 s) responde na hora
    h, calls = sequence(("ok", 5.0), ("ok", 0.0))
    t0 = time.perf_counter()
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.OK
    assert time.perf_counter() - t0 < 0.6
    assert any(a.hedge and a.outcome == "ok" for a in out.attempts)
    assert any(a.outcome == "cancelada" for a in out.attempts)


async def test_timeout_curto_corta_chamada_lenta():
    h, _ = sequence(("ok", 5.0))
    t0 = time.perf_counter()
    out = await make(h).cotar(PAYLOAD)
    assert out.status is QuoteStatus.INDISPONIVEL
    assert time.perf_counter() - t0 < 2.5
    assert {a.outcome for a in out.attempts} == {"timeout"}


async def test_cache_devolve_mesma_cotacao_sem_nova_chamada():
    h, calls = sequence(("ok", 0))
    c = make(h)
    a = await c.cotar(PAYLOAD)
    b = await c.cotar({**PAYLOAD, "plano_id": "COMPLETO"})  # normalização
    assert b.from_cache and b.quote_id == a.quote_id and b.quote == a.quote
    assert calls["n"] == 1


async def test_circuit_breaker_conta_cotacoes_e_abre():
    h, calls = sequence(("500", 0))
    c = make(h, breaker_failure_threshold=2, breaker_reset_s=60)
    assert (await c.cotar(PAYLOAD)).status is QuoteStatus.INDISPONIVEL
    assert await c.breaker.state() == "fechado"  # 4 tentativas = 1 cotação falha
    assert (await c.cotar({**PAYLOAD, "idade": 40})).status is QuoteStatus.INDISPONIVEL
    n = calls["n"]
    third = await c.cotar({**PAYLOAD, "idade": 41})
    assert third.status is QuoteStatus.CIRCUITO_ABERTO and calls["n"] == n
    assert await c.breaker.state() == "aberto"


async def test_circuit_breaker_meio_aberto_fecha_com_sucesso():
    h, _ = sequence(("500", 0), ("500", 0), ("500", 0), ("ok", 0))
    c = make(h, breaker_failure_threshold=1, breaker_reset_s=0.05, quote_max_attempts=3)
    assert (await c.cotar(PAYLOAD)).status is QuoteStatus.INDISPONIVEL
    await asyncio.sleep(0.06)
    assert (await c.cotar(PAYLOAD)).status is QuoteStatus.OK
    assert await c.breaker.state() == "fechado"


async def test_meio_aberto_deixa_passar_uma_unica_sonda():
    h, calls = sequence(("500", 0))
    c = make(h, breaker_failure_threshold=1, breaker_reset_s=1)
    await c.cotar(PAYLOAD)
    await asyncio.sleep(1.05)
    n = calls["n"]
    outs = await asyncio.gather(*[c.cotar({**PAYLOAD, "idade": 30 + i}) for i in range(10)])
    assert calls["n"] - n == 1  # uma sonda, com uma tentativa
    assert sum(o.status is QuoteStatus.CIRCUITO_ABERTO for o in outs) == 9
    assert await c.breaker.state() == "aberto"  # sonda falhou: reabre


async def test_200_com_corpo_invalido_nao_vira_cotacao_nem_cache():
    calls = {"n": 0}

    async def h(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text="<html>proxy</html>")
        return httpx.Response(200, json=OK_BODY)

    c = make(h)
    out = await c.cotar(PAYLOAD)
    assert out.status is QuoteStatus.OK and out.quote == OK_BODY
    assert out.attempts[0].outcome == "resposta_invalida"


@pytest.mark.parametrize("cep", ["26703384", "26703-384"])
async def test_normaliza_cep(cep):
    captured = {}

    async def h(request):
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    await make(h).cotar({**PAYLOAD, "cep": cep})
    assert captured["cep"] == "26703-384"
