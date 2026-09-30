"""Simulador de leads (etapa 6) e base da avaliação (etapa 8).

Cada lead nasce de um caso da Gold (dataset real, mascarado): idade, ano do carro,
região do CEP e o desfecho original da conversa (ganho, perdido, em negociação,
sem resposta), que vira comportamento (aceita, objeta, pede humano, some).

Dois "cérebros" de lead com a mesma interface:
- LeadRoteiro: determinístico, responde pelo que o bot perguntou. Reproduzível; usado na
  avaliação e na CI.
- LeadFastAgent: fast-agent com LLM (Groq) interpretando a persona; conversa livre, para
  estressar o extrator. Precisa de rede e chave.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

PLANOS = ("essencial", "completo", "premium")


@dataclass
class Persona:
    case_id: str
    idade: int
    veiculo_ano: int
    veiculo_texto: str
    cep: str | None
    plano: str
    desfecho: str  # ganho | perdido | em_negociacao | sem_resposta
    api_esperada: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_gold(cls, caso: dict[str, Any], seed: int = 0) -> Persona:
        rnd = random.Random(f"{caso['case_id']}:{seed}")  # noqa: S311 - sorteio de persona, não é segurança
        esp = caso["slots_esperados"]
        veic = next(
            (m for m in caso["lead_script"] if str(esp["veiculo_ano"]) in m and "anos" not in m),
            f"um carro {esp['veiculo_ano']}",
        )
        return cls(
            case_id=caso["case_id"],
            idade=esp["idade"],
            veiculo_ano=esp["veiculo_ano"],
            veiculo_texto=veic,
            cep=esp.get("cep"),
            plano=rnd.choice(PLANOS),
            desfecho=caso["outcome_original"],
            api_esperada=caso["api_esperada"],
        )

    @property
    def elegivel(self) -> bool:
        return self.api_esperada.get(self.plano, {}).get("status") == 200

    def premio_esperado(self, plano: str | None = None) -> float | None:
        r = self.api_esperada.get(plano or self.plano, {})
        return r.get("resposta", {}).get("premio_mensal") if r.get("status") == 200 else None


class Lead(Protocol):
    async def abrir(self) -> str: ...
    async def responder(self, bot: str) -> str | None: ...  # None = o lead some


class LeadRoteiro:
    """Responde de forma direta ao que o bot perguntou, como um lead objetivo do dataset."""

    def __init__(self, p: Persona) -> None:
        self.p = p
        self.objecoes = 0

    async def abrir(self) -> str:
        return "Oi, queria fazer um seguro pro meu carro"

    async def responder(self, bot: str) -> str | None:
        b = bot.lower()
        if "cotação pronta" in b or "consegui!" in b:
            match self.p.desfecho:
                case "ganho":
                    return "fechado!"
                case "perdido":
                    self.objecoes += 1
                    return (
                        "achei caro, a Porto Seguro me ofereceu menos" if self.objecoes > 1 else "achei caro"
                    )
                case "em_negociacao":
                    self.objecoes += 1
                    return "preciso pensar, achei caro" if self.objecoes == 1 else "vou pensar e te falo"
                case _:
                    return None  # sem resposta: some depois da cotação
        if "está certo?" in b:
            return "sim"
        if "modelo e o ano" in b or "ano do carro" in b:
            return self.p.veiculo_texto
        if "sua idade" in b:
            return f"tenho {self.p.idade} anos"
        if "cep" in b:
            return f"o carro fica no cep {self.p.cep}" if self.p.cep else "não sei o cep"
        if "qual plano" in b or "qual deles" in b or "quais planos" in b:
            return f"quero o {self.p.plano}"
        if "a partir de quando" in b or "data de início" in b:
            return "pode ser hoje"
        if "por escrito" in b:
            return "ok"
        if "ainda estou tentando" in b or "tentando de novo" in b:
            return None  # espera a mensagem ativa
        return "ok"


class LeadFastAgent:
    """Lead interpretado por um LLM via fast-agent (modelo padrão: Groq gpt-oss-20b)."""

    def __init__(self, p: Persona, model: str = "groq.openai/gpt-oss-20b") -> None:
        self.p, self.model = p, model
        self._ctx = None
        self._app = None

    def _instrucao(self) -> str:
        return (
            "Você é um cliente brasileiro no WhatsApp cotando seguro do seu carro. Escreva como gente de "
            "verdade: curto, informal, às vezes sem pontuação. Responda SÓ o que o atendente perguntou.\n"
            f"Seu carro: {self.p.veiculo_texto}. Sua idade: {self.p.idade}. CEP onde o carro dorme: "
            f"{self.p.cep}. Plano que você quer: {self.p.plano}.\n"
            f"Comportamento: {self._comportamento()}\nNunca invente CPF, e-mail ou telefone."
        )

    def _comportamento(self) -> str:
        return {
            "ganho": "se gostar da cotação, feche.",
            "perdido": "ache caro e cite que um concorrente ofereceu menos.",
            "em_negociacao": "diga que achou caro e que vai pensar.",
        }.get(self.p.desfecho, "depois da cotação, pare de responder (responda só 'FIM').")

    async def _garantir(self):
        if self._app is None:
            from fast_agent import FastAgent

            fast = FastAgent(f"lead-{self.p.case_id}", parse_cli_args=False, quiet=True)

            @fast.agent(name="lead", instruction=self._instrucao(), model=self.model)
            async def _lead():  # pragma: no cover - só declara o agente
                pass

            self._ctx = fast.run()
            self._app = await self._ctx.__aenter__()
        return self._app

    @staticmethod
    def _checa(txt: str) -> str:
        # o fast-agent devolve o erro do provedor como texto; não pode virar fala do lead
        if txt.startswith("I hit an internal error"):
            raise RuntimeError(f"LLM do lead falhou: {txt[:160]}")
        return txt

    async def abrir(self) -> str:
        app = await self._garantir()
        return self._checa(await app.lead.send("Mande a primeira mensagem para a seguradora."))

    async def responder(self, bot: str) -> str | None:
        app = await self._garantir()
        txt = self._checa((await app.lead.send(f"Atendente: {bot}")).strip())
        # avaliação com Groq: o lead respondeu "sim\nFIM" e o "sim" virou fechamento
        return None if not txt or re.search(r"\bFIM\W*$", txt) else txt

    async def fechar(self) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
