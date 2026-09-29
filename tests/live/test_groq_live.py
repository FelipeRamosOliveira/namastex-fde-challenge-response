"""Teste AO VIVO com o Groq (marcador `llm`). Roda só com GROQ_API_KEY e rede liberada:
uv run pytest -m llm tests/live
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from autoseguro.agent.llm_extract import LLMExtractor
from autoseguro.config import Settings
from autoseguro.guardrails.pii import PiiVault, mask
from autoseguro.llm.client import LLMClient, providers_from_settings
from autoseguro.tools.store import MemoryStore

pytestmark = pytest.mark.llm
GOLD = Path(__file__).resolve().parents[2] / "data" / "gold" / "cases.jsonl"


@pytest.fixture(scope="module")
def llm():
    s = Settings()
    providers = [p for p in providers_from_settings(s) if p.name == "groq"]
    if not providers:
        pytest.skip("GROQ_API_KEY não definida")
    try:
        httpx.get(
            "https://api.groq.com/openai/v1/models",
            timeout=5,
            headers={"Authorization": f"Bearer {providers[0].api_key}"},
        ).raise_for_status()
    except httpx.HTTPError as e:
        pytest.skip(f"Groq inacessível: {e}")
    return LLMClient(providers, MemoryStore(), timeout_s=15)


async def test_extracao_ao_vivo_na_gold(llm):
    casos = [json.loads(line) for line in GOLD.read_text().splitlines()][:40]
    ex = LLMExtractor(llm)
    acertos = total = via_llm = 0
    for c in casos:
        slots, vault = {}, PiiVault()
        aguardando = "veiculo_ano"
        for msg in c["lead_script"]:
            r = await ex.extract(mask(msg, vault).text, aguardando, date.today())
            via_llm += r.fonte.startswith("llm")
            slots.update(r.slots)
            aguardando = "idade" if "veiculo_ano" in slots else "veiculo_ano"
        for k in ("idade", "veiculo_ano"):
            total += 1
            acertos += slots.get(k) == c["slots_esperados"][k]
    assert via_llm > 0, "nenhuma extração passou pelo LLM"
    assert acertos / total >= 0.95, acertos / total
