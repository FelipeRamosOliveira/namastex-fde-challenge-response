import json
from datetime import date
from pathlib import Path

import pytest

from autoseguro.agent.extract import RuleExtractor, parse_data
from autoseguro.agent.templates import apresentar, brl, valores_permitidos
from autoseguro.guardrails.output import check_output
from autoseguro.guardrails.pii import PiiVault, mask

HOJE = date(2026, 9, 29)
GOLD = Path(__file__).resolve().parents[2] / "data" / "gold" / "cases.jsonl"
ex = RuleExtractor()


@pytest.mark.parametrize(
    ("texto", "awaiting", "esperado"),
    [
        ("Toyota Corolla 2008", None, {"veiculo_ano": 2008}),
        ("tenho 35 anos", None, {"idade": 35}),
        ("35", "idade", {"idade": 35}),
        ("quero começar em 2026-10-15", None, {"data_inicio": date(2026, 10, 15)}),
        ("meu carro tem 12 anos", None, {}),
        ("o plano completo", None, {"plano_id": "completo"}),
        ("pode ser hoje", "data_inicio", {"data_inicio": HOJE}),
        ("dia 15", "data_inicio", {"data_inicio": date(2026, 10, 15)}),
        ("15/11", "data_inicio", {"data_inicio": date(2026, 11, 15)}),
        ("nasci em 1985", "idade", {}),
        ("nasci em 1985", "veiculo_ano", {}),
        ("tenho 5 anos de carteira", "idade", {}),
        ("meu carro é um gol 2020 e tenho 30 anos", None, {"veiculo_ano": 2020, "idade": 30}),
        ("o carro tem 8 anos e eu tenho 41 anos", None, {"idade": 41}),
        ("quero o mais completo", None, {"plano_id": "premium"}),
        ("tenho 150 anos", None, {}),
        ("2019", "veiculo_ano", {"veiculo_ano": 2019}),
        ("em 2019 eu mudei de emprego", None, {}),
        ("moro no [CEP_1] mas o carro dorme no [CEP_2]", None, {"cep": "[CEP_2]"}),
        # vistos no teste ao vivo com Docker + Groq (29/09/2026)
        ("pode ser a partir de semana que vem", "data_inicio", {"data_inicio": date(2026, 10, 6)}),
        ("pode ser mês que vem", "data_inicio", {"data_inicio": date(2026, 10, 1)}),
        ("pode ser", "data_inicio", {"data_inicio": HOJE}),
        ("quero o top, o mais barato não serve", "plano_id", {}),
        ("não quero o premium, quero o completo", "plano_id", {"plano_id": "completo"}),
        # vistos no teste de deploy externo com Docker + Groq (30/09/2026); HOJE é uma terça
        ("tenho trinta e dois", "idade", {"idade": 32}),
        ("tenho trinta e dois anos", None, {"idade": 32}),
        ("setenta e cinco anos de idade", None, {"idade": 75}),
        ("pode ser a partir de segunda que vem", "data_inicio", {"data_inicio": date(2026, 10, 5)}),
        ("segunda-feira", "data_inicio", {"data_inicio": date(2026, 10, 5)}),
        ("terça", "data_inicio", {"data_inicio": date(2026, 10, 6)}),  # hoje é terça: a próxima
        ("sexta da semana que vem", "data_inicio", {"data_inicio": date(2026, 10, 9)}),
        ("é do ano passado", None, {"veiculo_ano": 2025}),
        ("ano passado", "veiculo_ano", {"veiculo_ano": 2025}),
        ("um hb20 zero km", None, {"veiculo_ano": 2026}),
        ("comprei um hb20 ano passado", None, {}),  # ano da compra, não do modelo
        ("comprei ano passado", "veiculo_ano", {}),
        ("um gol, tenho um filho", None, {}),  # "um" é artigo, não número
    ],
)
async def test_extrai_slots(texto, awaiting, esperado):
    r = await ex.extract(texto, awaiting, HOJE)
    assert r.slots == esperado


@pytest.mark.parametrize(
    ("texto", "intent"),
    [
        ("quero falar com um atendente", "pedido_humano"),
        ("bati o carro ontem, como abro sinistro?", "fora_de_escopo"),
        ("fechado!", "aceite"),
        ("o preco ta salgado", "objecao_preco"),
        ("a Azul me ofereceu menos", "concorrente"),
        ("quais planos voces tem?", "pergunta_planos"),
        ("Não, prefiro ver outro.", "pergunta_planos"),
        ("quero ver outro plano", "pergunta_planos"),
        ("[audio] mensagem de voz (18s)", "midia"),
        ("[image] foto.jpg", "midia"),
        ("[document] cnh.pdf", "midia"),
    ],
)
async def test_intencoes(texto, intent):
    assert intent in (await ex.extract(texto, None, HOJE)).intents


def test_recusa_sem_texto_cru_da_api():
    from autoseguro.agent.templates import recusa

    idade = recusa("Idade acima do limite de aceitacao (75 anos).")
    assert "condutor (limite de 75 anos)" in idade and "aceitacao" not in idade
    assert "ano do carro (limite de 20 anos)" in recusa("Veiculo com mais de 20 anos nao e aceito.")
    assert "ano do carro" in recusa("Idade do veiculo fora das faixas aceitas.")


def test_anotado_e_reperguntar():
    from autoseguro.agent.templates import anotado, reperguntar

    assert anotado({"cep", "plano_id"}, {"plano_id": "completo"}) == "Anotei o CEP e o plano Completo. "
    assert anotado(set(), {}) == ""
    assert (
        reperguntar("veiculo_ano") == "Pra fazer a cotação, ainda preciso saber o ano do carro (ex.: 2021)."
    )
    assert reperguntar("idade") == "Pra fazer a cotação, ainda preciso saber a sua idade."


def test_parse_data_passada_vira_proximo_ano():
    assert parse_data("10/01", HOJE) == date(2027, 1, 10)


@pytest.mark.skipif(not GOLD.exists(), reason="rode o pipeline gold")
async def test_acerto_extracao_na_gold():
    """Idade e ano do veículo extraídos das mensagens reais (mascaradas) do dataset."""
    casos = [json.loads(line) for line in GOLD.read_text().splitlines()]
    acertos = total = 0
    for c in casos:
        slots = {}
        for msg in c["lead_script"]:
            m = mask(msg, PiiVault()).text  # como no grafo: guardrail antes do extrator
            slots.update((await ex.extract(m, None, HOJE)).slots)
        esp = c["slots_esperados"]
        for k in ("idade", "veiculo_ano"):
            total += 1
            acertos += slots.get(k) == esp[k]
        total += 1
        acertos += bool(slots.get("cep")) == bool(esp.get("cep"))
    assert acertos / total >= 0.95, acertos / total


QUOTE = {
    "plano_id": "completo",
    "plano_nome": "Completo",
    "premio_mensal": 395.66,
    "franquia": 3000,
    "coberturas": ["colisao", "roubo"],
    "carencia": {"coberturas": ["roubo"], "dias": 30},
    "primeiro_pagamento_pro_rata": {
        "dias_no_mes": 31,
        "dias_cobrados": 17,
        "valor_primeiro_pagamento": 216.97,
    },
}


def test_brl():
    assert brl(3000) == "R$ 3.000,00" and brl(395.66) == "R$ 395,66"


def test_template_passa_no_guardrail():
    assert check_output(apresentar(QUOTE), valores_permitidos([QUOTE])).ok


@pytest.mark.parametrize(
    "texto",
    [
        "Seu plano sai por R$ 99,90 por mês",  # valor inventado
        "Consigo R$ 350 pra você",  # sem centavos, inventado
        "Confirma o cpf 389.083.863-43?",  # PII
        "Seu email [EMAIL_1] está certo?",  # token exposto
    ],
)
def test_guardrail_saida_bloqueia(texto):
    assert not check_output(texto, valores_permitidos([QUOTE])).ok


def test_guardrail_saida_aceita_valor_da_api_sem_centavos():
    assert check_output("franquia de R$ 3.000", valores_permitidos([QUOTE])).ok


def test_todos_os_textos_fixos_passam_no_guardrail():
    """Nenhum template pode ser bloqueado pelo próprio guardrail (senão o lead recebe o fallback)."""
    from autoseguro.agent import templates as T

    planos = [{"nome": "Essencial", "coberturas": ["colisao"]}]
    textos = [
        T.saudacao() + T.perguntar(c, planos)
        for c in ("veiculo_ano", "idade", "cep", "plano_id", "data_inicio")
    ]
    textos += [
        T.confirmar(
            {"veiculo_ano": 2020, "idade": 35, "plano_id": "completo", "data_inicio": "2026-10-15"}, "01"
        )
    ]
    textos += list(T.HANDOFF.values()) + [
        T.recusa("Idade acima do limite de aceitacao (75 anos)."),
        T.POS_HANDOFF,
        T.PEDIR_TEXTO,
        T.CORRIGIR,
        T.FALLBACK_SEGURO,
    ]
    for t in textos:
        chk = check_output(t, set())
        assert chk.ok, (t, chk.violacoes)
