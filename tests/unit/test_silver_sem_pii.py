"""Prova de que a Silver não carrega PII da Bronze.

A checagem é independente do guardrail: extrai os valores sensíveis da Bronze
com regex simples e procura cada valor (e só seus dígitos) na Silver inteira.
"""

import re

import pandas as pd
import pytest

from autoseguro.data.pipeline import BRONZE, load_bronze, normaliza_veiculo, to_silver

pytestmark = pytest.mark.skipif(not BRONZE.exists(), reason="submódulo vendor/challenge ausente")

SIMPLES = {
    "cpf": r"\d{3}\.\d{3}\.\d{3}-\d{2}",
    "email": r"\S+@\S+\.\w+",
    "telefone": r"\+55 \d{2} 9\d{4}-\d{4}",
    "placa": r"\b[A-Z]{3}\d[A-Z]\d{2}\b",
    "cep": r"\b\d{5}-\d{3}\b",
}


@pytest.fixture(scope="module")
def bronze_silver():
    bronze = load_bronze()
    return bronze, to_silver(bronze)


def test_zero_pii_da_bronze_na_silver(bronze_silver):
    bronze, silver = bronze_silver
    texto_silver = "\n".join(silver.body_masked)
    digitos_silver = re.sub(r"\D", "", texto_silver)
    vazamentos = []
    for tipo, pat in SIMPLES.items():
        for valor in set(re.findall(pat, "\n".join(bronze.message_body))):
            if valor in texto_silver:
                vazamentos.append((tipo, valor))
            # mesmo número com outra pontuação (só para valores numéricos longos)
            dig = re.sub(r"\D", "", valor)
            if tipo in ("cpf", "telefone") and dig in digitos_silver:
                vazamentos.append((tipo + "_digitos", valor))
    assert vazamentos == []


def test_nomes_de_lead_nao_aparecem(bronze_silver):
    bronze, silver = bronze_silver
    for cid, conv in list(silver.groupby("conversation_id"))[:300]:
        nomes = bronze.loc[
            (bronze.conversation_id == cid) & (bronze.sender_role == "lead"), "sender_name"
        ].iloc[0]
        for parte in nomes.split():
            assert not re.search(rf"\b{parte}\b", " ".join(conv.body_masked)), (cid, parte)


def test_ordem_por_message_index(bronze_silver):
    _, silver = bronze_silver
    assert silver.groupby("conversation_id").message_index.apply(lambda s: s.is_monotonic_increasing).all()


def test_silver_sem_colunas_de_pii(bronze_silver):
    _, silver = bronze_silver
    assert not {"sender_name", "message_body", "veiculo_texto"} & set(silver.columns)
    assert silver.cep_prefixo.str.fullmatch(r"\d{2}").all()


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Toyota Corolla 2008", ("Toyota", "Corolla", 2008)),
        ("e um Sandero 2022", (None, "Sandero", 2022)),
        ("Toyota Corolla, ano 2008", ("Toyota", "Corolla", 2008)),
        ("Chevrolet Onix Plus 2019", ("Chevrolet", "Onix Plus", 2019)),
    ],
)
def test_normaliza_veiculo(texto, esperado):
    v = normaliza_veiculo(texto)
    assert (v["marca"], v["modelo"], v["ano"]) == esperado


def test_silver_parquet_roundtrip(tmp_path, bronze_silver):
    _, silver = bronze_silver
    p = tmp_path / "s.parquet"
    silver.head(50).to_parquet(p)
    assert len(pd.read_parquet(p)) == 50


def test_gold_sem_pii_da_bronze(bronze_silver):
    from autoseguro.data.pipeline import GOLD

    if not GOLD.exists():
        pytest.skip("rode o pipeline gold")
    bronze, _ = bronze_silver
    gold = GOLD.read_text(encoding="utf-8")
    for tipo, pat in SIMPLES.items():
        for valor in set(re.findall(pat, "\n".join(bronze.message_body))):
            assert valor not in gold, (tipo, valor)
    casos = gold.strip().splitlines()
    assert len(casos) >= 200
    assert '"status": 422' in gold  # há recusas reais na Gold
