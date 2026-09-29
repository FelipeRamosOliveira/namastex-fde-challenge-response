"""Cliente, regras e servidor MCP contra a quote-api ORIGINAL do desafio."""

import time
from datetime import date

import httpx
import pytest
from fastmcp import Client

from autoseguro.config import Settings
from autoseguro.tools.mcp_server import Services, build_server
from autoseguro.tools.quote_client import QuoteClient, QuoteStatus
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.integration


def settings(url, **kw):
    return Settings(_env_file=None, quote_api_url=url, **kw)


def client(url, **kw):
    return QuoteClient(settings(url, **kw), MemoryStore(), httpx.AsyncClient(base_url=url))


async def test_valores_batem_com_a_api_original(stable_quote_url):
    payload = {"plano_id": "completo", "idade": 35, "veiculo_ano": 2022, "cep": "01310-100"}
    out = await client(stable_quote_url).cotar(payload)
    direto = httpx.post(stable_quote_url + "/quote", json=payload).json()
    assert out.status is QuoteStatus.OK
    assert out.quote == direto  # nenhum valor transformado


async def test_pro_rata_e_carencia(stable_quote_url):
    inicio = date.today().replace(day=15).isoformat()
    out = await client(stable_quote_url).cotar(
        {"plano_id": "essencial", "idade": 40, "veiculo_ano": 2020, "data_inicio": inicio}
    )
    assert out.quote["primeiro_pagamento_pro_rata"]["dias_cobrados"] > 0
    assert out.quote["carencia"]["dias"] == 30


async def test_recusa_idade_uma_tentativa(stable_quote_url):
    out = await client(stable_quote_url).cotar({"plano_id": "completo", "idade": 80, "veiculo_ano": 2022})
    assert out.status is QuoteStatus.RECUSADA and len(out.attempts) == 1


async def test_api_fora_nao_devolve_preco(quote_api):
    with quote_api(failure=1.0) as url:
        out = await client(url).cotar({"plano_id": "completo", "idade": 35, "veiculo_ano": 2022})
    assert out.status is QuoteStatus.INDISPONIVEL and out.quote is None


async def test_api_lenta_falha_rapido(quote_api):
    with quote_api(slow=1.0, slow_seconds=8) as url:
        t0 = time.perf_counter()
        out = await client(url).cotar({"plano_id": "completo", "idade": 35, "veiculo_ano": 2022})
        elapsed = time.perf_counter() - t0
    assert out.status is QuoteStatus.INDISPONIVEL
    assert elapsed < 8  # nunca espera a lentidão de 8 s


async def test_instabilidade_padrao_resolve_rapido(quote_api):
    """Com a instabilidade padrão do desafio (20% falha, 10% lenta), 30 cotações seguidas."""
    with quote_api(failure=0.2, slow=0.1, seed=7) as url:
        c = client(url)
        lat, ok = [], 0
        for idade in range(30, 60):
            out = await c.cotar({"plano_id": "essencial", "idade": idade, "veiculo_ano": 2021})
            ok += out.status is QuoteStatus.OK
            lat.append(out.latency_ms)
    lat.sort()
    assert ok >= 29
    assert lat[int(len(lat) * 0.95) - 1] < 3000  # p95 abaixo de 3 s


async def test_mcp_ferramentas_em_processo(stable_quote_url):
    s = settings(stable_quote_url)
    services = Services.from_settings(s, store=MemoryStore())
    async with Client(build_server(services)) as mcp:
        nomes = {t.name for t in await mcp.list_tools()}
        assert {"consultar_planos", "pre_validar", "cotar", "registrar_handoff", "status_cotacao"} <= nomes

        pv = (await mcp.call_tool("pre_validar", {"idade": 80})).data
        assert pv["ok"] is False and pv["regra"] == "faixa_etaria"
        pv = (await mcp.call_tool("pre_validar", {"veiculo_ano": date.today().year - 25})).data
        assert pv["ok"] is False and pv["regra"] == "idade_veiculo"

        q = (await mcp.call_tool("cotar", {"plano_id": "premium", "idade": 30, "veiculo_ano": 2023})).data
        assert q["status"] == "ok" and q["quote"]["plano_id"] == "premium"

        planos = (await mcp.call_tool("consultar_planos", {})).data
        assert [p["id"] for p in planos["planos"]] == ["essencial", "completo", "premium"]

        ho = (
            await mcp.call_tool(
                "registrar_handoff",
                {
                    "conversation_id": "c1",
                    "motivo": "pedido_humano",
                    "resumo": "lead cpf 389.083.863-43 pediu humano",
                },
            )
        ).data
        assert "389.083.863-43" not in str(ho) and "[CPF_1]" in ho["resumo"]
