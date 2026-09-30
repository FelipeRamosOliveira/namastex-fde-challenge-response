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
        out = await agent.handle(cid, m)
        assert "Desculpa, tive um problema" not in out["reply"], (m, out)  # guardrail não bloqueou nada
        outs.append(out)
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
        assert "Qual é o modelo e o ano" in outs[0]["reply"]  # saudação não pode cair no fallback
        assert all("Desculpa, tive um problema" not in o["reply"] for o in outs)
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


async def test_api_fora_tenta_em_segundo_plano_e_depois_humano(quote_api, tmp_path):
    import asyncio

    with quote_api(failure=1.0) as url:
        s = cfg(url, tmp_path, quote_max_attempts=2, retry_fundo_delays_s=[0.1, 0.1])
        async with AutoSeguroAgent(s) as ag:
            await conversa(ag, "c6", FELIZ)
            r = await ag.handle("c6", "sim")
            assert r["stage"] == "aguardando_cotacao" and "R$" not in r["reply"]
            assert "tentando de novo" in r["reply"]
            for _ in range(50):  # espera as 2 novas tentativas em segundo plano e a entrega
                await asyncio.sleep(0.1)
                ativas = await ag.mensagens_ativas("c6")
                if ativas:
                    break
            t = await ag.trace("c6")
    assert t["stage"] == "handoff" and t["handoff"]["motivo"] == "cotacao_indisponivel"
    assert len([e for e in t["events"] if e["type"] == "cotacao"]) == 3  # 1 na hora + 2 em segundo plano
    assert ativas and "atendente" in ativas[-1]["texto"] and "R$" not in ativas[-1]["texto"]


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
    assert all(e["event_id"] and e["conversation_id"] == t["conversation_ref"] for e in t["events"])
    assert t["conversation_ref"].startswith("conv_")


async def test_rajada_na_mesma_conversa_nao_perde_dados(stable_quote_url, tmp_path):
    import asyncio

    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await ag.handle("c11", "oi")
        await asyncio.gather(
            ag.handle("c11", "é um corolla 2022"),
            ag.handle("c11", f"tenho 35 anos, cpf {CPF}"),
            ag.handle("c11", "cep 01310-100"),
        )
        t = await ag.trace("c11")
    assert {"veiculo_ano", "idade", "cep"} <= t["slots"].keys()
    assert len([m for m in t["transcript"] if m["role"] == "lead"]) == 4


async def test_cotacao_usa_o_cep_confirmado(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c12", ["oi", "Gol 2021", "tenho 40 anos"])
        r = await ag.handle("c12", "moro no 21000-000 mas o carro dorme no 01310-100")
        await conversa(ag, "c12", ["essencial", "hoje"])
        t = await ag.trace("c12")
        assert t["slots"]["cep"] == "01xxx-xxx"
        r = await ag.handle("c12", "sim")
    direto = httpx.post(
        stable_quote_url + "/quote",
        json={
            "plano_id": "essencial",
            "idade": 40,
            "veiculo_ano": 2021,
            "cep": "01310-100",
            "data_inicio": date.today().isoformat(),
        },
    ).json()
    assert brl(direto["premio_mensal"]) in r["reply"]


async def test_retomada_no_dia_seguinte_pede_nova_data(stable_quote_url, tmp_path):
    from datetime import timedelta

    s = cfg(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s) as ag:
        await conversa(ag, "c13", FELIZ)  # "hoje" = data de início
    amanha = date.today() + timedelta(days=1)
    async with AutoSeguroAgent(s, hoje=lambda: amanha) as ag2:
        r = await ag2.handle("c13", "sim")
    assert r["stage"] == "coletando" and "já passou" in r["reply"]


async def test_mudanca_de_dado_depois_da_cotacao_reconfirma(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c14", [*FELIZ, "sim"])
        r = await ag.handle("c14", "na verdade tenho 62 anos")
        assert r["stage"] == "confirmando" and "Idade 62" in r["reply"] and r["quote_id"] is None
        r = await ag.handle("c14", "sim")
    direto = httpx.post(
        stable_quote_url + "/quote",
        json={
            "plano_id": "completo",
            "idade": 62,
            "veiculo_ano": 2020,
            "cep": "01310-100",
            "data_inicio": date.today().isoformat(),
        },
    ).json()
    assert brl(direto["premio_mensal"]) in r["reply"]


async def test_imagem_e_documento_pelo_message_type(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await ag.handle("c15", "oi")
        r1 = await ag.handle("c15", "foto.jpg", message_type="image")
        assert "por escrito" in r1["reply"]
        r2 = await ag.handle("c15", "cnh.pdf", message_type="document")
    assert r2["handoff"]["motivo"] == "midia"


async def test_idade_absurda_nao_quebra(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await conversa(ag, "c16", ["oi", "Gol 2021"])
        r = await ag.handle("c16", "tenho 150 anos")
    assert r["stage"] == "coletando" and "idade" in r["reply"]


async def test_texto_bruto_nao_vai_para_o_checkpoint(stable_quote_url, tmp_path):
    s = cfg(stable_quote_url, tmp_path)
    async with AutoSeguroAgent(s) as ag:
        await ag.handle("5521972242584", f"oi, meu nome é Ana Souza, cpf {CPF}, email ana.s@gmail.com")
        await ag.handle("5521972242584", "quero falar com um atendente")
    blob = (tmp_path / "ck.sqlite").read_bytes()
    for sensivel in (CPF, "ana.s@gmail.com", "Souza", "5521972242584"):
        assert sensivel.encode() not in blob


async def test_mensagem_repetida_nao_reprocessa(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        a = await ag.handle("c17", "oi", message_id="m1")
        b = await ag.handle("c17", "oi", message_id="m1")
        t = await ag.trace("c17")
    assert b["reply"] == a["reply"] and b.get("duplicada")
    assert len(t["transcript"]) == 2


async def test_lista_de_planos_aparece_uma_vez(stable_quote_url, tmp_path):
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path)) as ag:
        await ag.handle("c18", "oi")
        r1 = await ag.handle("c18", "quais planos vocês têm? é um gol 2020")
        await ag.handle("c18", "tenho 40 anos")
        r3 = await ag.handle("c18", "cep 01310-100")
    assert "Temos 3 planos" in r1["reply"]
    assert "Temos 3 planos" not in r3["reply"] and "Essencial, Completo ou Premium" in r3["reply"]


async def test_cep_cifrado_no_checkpoint_com_vault_key(stable_quote_url, tmp_path):
    from cryptography.fernet import Fernet

    from autoseguro.guardrails.pii import configurar_chave_vault

    s = cfg(stable_quote_url, tmp_path, vault_key=Fernet.generate_key().decode())
    try:
        async with AutoSeguroAgent(s) as ag:
            outs = await conversa(ag, "c19", [*FELIZ, "sim"])
        assert outs[-1]["stage"] == "cotado"  # o CEP foi decifrado para cotar
        blob = (tmp_path / "ck.sqlite").read_bytes()
        assert b"01310-100" not in blob and b"01310100" not in blob
    finally:
        configurar_chave_vault(None)


async def test_data_que_ja_passou_e_explicada(stable_quote_url, tmp_path):
    """Avaliação com Groq: "01/10/2024" era descartada em silêncio e a pergunta se repetia."""
    async with AutoSeguroAgent(cfg(stable_quote_url, tmp_path), hoje=lambda: date(2026, 9, 30)) as ag:
        await conversa(ag, "c-data", ["Gol 2021, tenho 35 anos, cep 01310-100, plano completo"])
        r = await ag.handle("c-data", "01/10/2024")
        assert r["reply"].startswith("A data 01/10/2024 já passou (hoje é 30/09/2026).")
        r = await ag.handle("c-data", "então amanhã")
        assert r["stage"] == "confirmando" and "Início em 01/10/2026" in r["reply"]
        r = await ag.handle("c-data", "início 01/10/2024")  # na confirmação também
        assert r["stage"] == "coletando" and "já passou" in r["reply"]
