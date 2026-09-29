"""Pipeline de dados em camadas (medalhão) sobre o dataset do desafio.

Bronze: parquet original, sem alteração (vendor/challenge/dataset).
Silver: mensagens ordenadas por message_index, PII mascarada, veículo normalizado,
        CEP generalizado para o prefixo de 2 dígitos (é o que afeta o preço).
Gold:   casos de avaliação (roteiro do lead + resultado esperado). O resultado
        esperado vem da API REAL do desafio, chamada com falha zero, nunca de conta própria.

Uso:
    uv run python -m autoseguro.data.pipeline silver
    uv run python -m autoseguro.data.pipeline gold --quote-url http://localhost:8000 --n 300
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

from autoseguro.guardrails.pii import PiiKind, PiiVault, mask, scan

ROOT = Path(__file__).resolve().parents[3]
BRONZE = ROOT / "vendor" / "challenge" / "dataset" / "conversations.parquet"
SILVER = ROOT / "data" / "silver" / "conversations.parquet"
GOLD = ROOT / "data" / "gold" / "cases.jsonl"
PROFILE = ROOT / "data" / "gold" / "profile.json"

PLANOS = ("essencial", "completo", "premium")
MARCAS = {
    "volkswagen",
    "vw",
    "chevrolet",
    "fiat",
    "hyundai",
    "toyota",
    "honda",
    "jeep",
    "renault",
    "ford",
    "nissan",
    "peugeot",
    "citroen",
    "citroën",
    "kia",
    "mitsubishi",
}


def load_bronze(path: Path = BRONZE) -> pd.DataFrame:
    return pd.read_parquet(path)


def pseudonimo(prefix: str, valor: str) -> str:
    return f"{prefix}_{hashlib.sha256(valor.encode()).hexdigest()[:8]}"


def normaliza_veiculo(texto: str | None) -> dict:
    """'e um Sandero 2022' / 'Toyota Corolla, ano 2008' -> marca, modelo, ano."""
    if not texto:
        return {"marca": None, "modelo": None, "ano": None}
    ano_m = re.search(r"\b(19[5-9]\d|20\d{2})\b", texto)
    limpo = re.sub(r"\b(e um|é um|ano|um|uma)\b|[,]", " ", texto, flags=re.IGNORECASE)
    limpo = re.sub(r"\b(19[5-9]\d|20\d{2})\b", " ", limpo)
    partes = limpo.split()
    marca = partes[0] if partes and partes[0].lower() in MARCAS else None
    modelo = " ".join(partes[1:] if marca else partes) or None
    return {"marca": marca, "modelo": modelo, "ano": int(ano_m.group(1)) if ano_m else None}


def to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena, mascara e normaliza. Não guarda nenhum valor original de PII."""
    df = df.sort_values(["conversation_id", "message_index"]).reset_index(drop=True)
    rows = []
    for cid, conv in df.groupby("conversation_id", sort=False):
        vault = PiiVault()
        lead_names = conv.loc[conv.sender_role == "lead", "sender_name"].dropna().unique().tolist()
        veic = normaliza_veiculo(conv["veiculo_texto"].iloc[0])
        cep_prefixos = [
            re.sub(r"\D", "", e.value)[:2]
            for body in conv.message_body
            for e in scan(str(body))
            if e.kind is PiiKind.CEP
        ]
        for r in conv.itertuples():
            body = mask(str(r.message_body), vault, names=lead_names).text
            rows.append(
                {
                    "conversation_id": cid,
                    "message_index": int(r.message_index),
                    "timestamp_original": r.timestamp,  # fora de ordem na origem; ordem = message_index
                    "sender_role": r.sender_role,
                    "sender_id": pseudonimo(r.sender_role, str(r.sender_name)),
                    "message_type": r.message_type,
                    "is_media": r.message_type != "text",
                    "body_masked": body,
                    "conversation_outcome": r.conversation_outcome,
                    "lead_idade": int(r.lead_idade_informada) if pd.notna(r.lead_idade_informada) else None,
                    "veiculo_marca": veic["marca"],
                    "veiculo_modelo": veic["modelo"],
                    "veiculo_ano": veic["ano"],
                    "cep_prefixo": cep_prefixos[0] if cep_prefixos else None,
                    "pii_tokens": sorted({t.split("_")[0].strip("[") for t in vault.tokens}),
                }
            )
    return pd.DataFrame(rows)


def cep_generalizado(prefixo: str | None) -> str | None:
    """CEP sintético com o mesmo prefixo: preserva o preço e não carrega o CEP real."""
    return f"{prefixo}000-000" if prefixo else None


def script_do_lead(conv: pd.DataFrame) -> list[str]:
    """Mensagens do lead (mascaradas) com o token de CEP trocado pelo CEP generalizado."""
    cep = cep_generalizado(conv["cep_prefixo"].iloc[0])
    msgs = []
    for body in conv.loc[conv.sender_role == "lead", "body_masked"]:
        if cep:
            body = re.sub(r"\[CEP_\d+\]", cep, body)
        msgs.append(body)
    return msgs


async def _cotar_real(client: httpx.AsyncClient, payload: dict) -> dict:
    r = await client.post("/quote", json=payload)
    if r.status_code == 200:
        return {"status": 200, "resposta": r.json()}
    if r.status_code == 422:
        return {"status": 422, "motivo": r.json().get("motivo")}
    raise RuntimeError(
        f"API respondeu {r.status_code}; rode a quote-api com QUOTE_FAILURE_RATE=0 para gerar a Gold"
    )


async def build_gold(silver: pd.DataFrame, quote_url: str, n: int = 300, seed: int = 42) -> list[dict]:
    convs = silver.groupby("conversation_id", sort=True)
    meta = convs.first()
    # Estratifica por desfecho e garante casos de recusa (idade > 75 ou veículo > 20 anos)
    ano_ref = date.today().year
    meta["recusa_esperada"] = (meta.lead_idade > 75) | ((ano_ref - meta.veiculo_ano) > 20)
    amostra = (
        meta.groupby(["conversation_outcome", "recusa_esperada"], group_keys=False)
        .apply(lambda g: g.sample(min(len(g), max(1, round(n * len(g) / len(meta)))), random_state=seed))
        .index.tolist()
    )
    cases = []
    async with httpx.AsyncClient(base_url=quote_url, timeout=15) as client:
        for cid in sorted(amostra):
            conv = silver[silver.conversation_id == cid]
            m = meta.loc[cid]
            base = {"idade": int(m.lead_idade), "veiculo_ano": int(m.veiculo_ano)}
            cep = cep_generalizado(m.cep_prefixo)
            if cep:
                base["cep"] = cep
            esperado = {p: await _cotar_real(client, {**base, "plano_id": p}) for p in PLANOS}
            cases.append(
                {
                    "case_id": cid,
                    "data_referencia": date.today().isoformat(),
                    "outcome_original": m.conversation_outcome,
                    "lead_script": script_do_lead(conv),
                    "tem_midia": bool(conv.is_media.any()),
                    "slots_esperados": {**base, "cep_prefixo": m.cep_prefixo},
                    "api_esperada": esperado,
                }
            )
    return cases


def profile(silver: pd.DataFrame) -> dict:
    convs = silver.groupby("conversation_id").first()
    ano_ref = date.today().year
    lead = silver[silver.sender_role == "lead"]
    objecoes = Counter()
    for body in lead.body_masked:
        b = body.lower()
        for k in (
            "preco",
            "preço",
            "caro",
            "salgado",
            "franquia",
            "concorrente",
            "mais barato",
            "pensar",
            "esposa",
        ):
            if k in b:
                objecoes[k] += 1
    return {
        "mensagens": len(silver),
        "conversas": len(convs),
        "desfechos": convs.conversation_outcome.value_counts().to_dict(),
        "tipos_mensagem": silver.message_type.value_counts().to_dict(),
        "leads_acima_75": int((convs.lead_idade > 75).sum()),
        "veiculos_acima_20_anos": int(((ano_ref - convs.veiculo_ano) > 20).sum()),
        "cep_prefixos": convs.cep_prefixo.value_counts().to_dict(),
        "palavras_de_objecao": dict(objecoes.most_common()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["silver", "gold", "all"])
    ap.add_argument("--quote-url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=300)
    a = ap.parse_args()

    if a.stage in ("silver", "all"):
        silver = to_silver(load_bronze())
        SILVER.parent.mkdir(parents=True, exist_ok=True)
        silver.to_parquet(SILVER, index=False)
        print(f"silver: {len(silver)} mensagens -> {SILVER.relative_to(ROOT)}")
    if a.stage in ("gold", "all"):
        silver = pd.read_parquet(SILVER)
        cases = asyncio.run(build_gold(silver, a.quote_url, a.n))
        GOLD.parent.mkdir(parents=True, exist_ok=True)
        GOLD.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
        PROFILE.write_text(json.dumps(profile(silver), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"gold: {len(cases)} casos -> {GOLD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
