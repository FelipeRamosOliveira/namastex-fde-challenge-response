"""Simulador de leads contra o agente em processo e a quote-api original (sem instabilidade)."""

import pytest

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.config import Settings
from autoseguro.sim.avaliar import avaliar

pytestmark = pytest.mark.integration


async def test_simulador_roda_casos_da_gold(stable_quote_url, tmp_path):
    s = Settings(_env_file=None, quote_api_url=stable_quote_url, checkpoint_db=str(tmp_path / "s.sqlite"))
    async with AutoSeguroAgent(s) as ag:
        m, res = await avaliar(lambda c, t: ag.handle(c, t), ag.mensagens_ativas, n=40, concorrencia=8)
    assert m["conversas"] == 40
    assert m["taxa_ponta_a_ponta"] >= 0.95, m
    assert m["taxa_acerto_preco"] == 1.0, m
    assert m["vazamento_pii_respostas"] == 0
    assert "recusa_regra" in m["handoffs"]  # há casos inelegíveis na Gold


async def test_lead_que_diz_fim_depois_de_outra_palavra_sai():
    """Avaliação com Groq: o lead respondeu "sim\nFIM" e o "sim" virou fechamento."""
    from autoseguro.sim.leads import LeadFastAgent

    ld = LeadFastAgent.__new__(LeadFastAgent)

    class App:
        class lead:  # noqa: N801 - imita o fast-agent
            @staticmethod
            async def send(_):
                return "sim  \nFIM"

    ld._app = App()
    assert await ld.responder("Cotação pronta!") is None
