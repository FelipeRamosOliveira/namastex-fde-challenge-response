"""Extração de dados e intenções a partir do texto JÁ MASCARADO.

Etapa 3: extrator por regras (determinístico, sem LLM). Na etapa 4 um extrator com
LLM implementa a mesma interface `Extractor` e este vira o plano B quando o LLM falha.

Cuidados que motivaram as regras (erros vistos na solução concorrente):
- "quero começar em 2026-10-15" NÃO é ano do veículo;
- "meu carro tem 12 anos" NÃO é a idade do condutor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

CAMPOS = ("veiculo_ano", "idade", "cep", "plano_id", "data_inicio")


@dataclass
class Extraction:
    slots: dict[str, object] = field(default_factory=dict)
    intents: set[str] = field(default_factory=set)
    # intents: saudacao, pedido_humano, fora_de_escopo, aceite, negacao, objecao_preco,
    #          concorrente, pergunta_planos, midia


class Extractor(Protocol):
    async def extract(self, text: str, awaiting: str | None, hoje: date) -> Extraction: ...


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


_RE_DATA_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_RE_DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_RE_DIA = re.compile(r"\bdia (\d{1,2})\b")
_RE_ANO = re.compile(r"(?<![\d/-])(19[5-9]\d|20\d{2})(?![\d/-])")
_RE_IDADE = [
    re.compile(r"\btenho (\d{1,3}) anos\b"),
    re.compile(r"\b(\d{1,3}) anos de idade\b"),
    re.compile(r"\bidade(?: e| eh| de|:)? (\d{1,3})\b"),
    re.compile(r"\bminha idade(?: e| eh|:)? (\d{1,3})\b"),
]
_RE_CEP_TOKEN = re.compile(r"\[CEP_\d+\]")
_RE_CEP_NUM = re.compile(r"(?<!\d)(\d{5}-?\d{3})(?!\d)")

_PLANOS = {
    "essencial": ["essencial", "basico", "mais barato", "mais em conta"],
    "completo": ["completo"],
    "premium": ["premium", "mais completo de todos", "top"],
}
_INTENTS = {
    "pedido_humano": [
        r"\bhumano\b",
        r"\batendente\b",
        r"\bpessoa (de verdade|real)\b",
        r"\bfalar com (alguem|um vendedor|o vendedor|uma pessoa)\b",
        r"\bvendedor\b",
    ],
    "fora_de_escopo": [
        r"\bsinistro\b",
        r"\bbati\b",
        r"\bbateram\b",
        r"\bacidente\b",
        r"\bcancelar\b",
        r"\bseguro (de )?(vida|residencial|casa|moto)\b",
        r"\bsegunda via\b",
        r"\bboleto atrasado\b",
    ],
    "aceite": [
        r"^(sim|s|isso|ok|certo|correto|confirmo|pode|pode ser|beleza|blz|perfeito|exato)\b",
        r"\bfechad[oa]\b",
        r"\bvamos nessa\b",
        r"\bpode emitir\b",
        r"\bquero (contratar|fechar)\b",
        r"\bgostei\b",
        r"\best[aá] certo\b",
    ],
    "negacao": [r"^(nao|n|errado|incorreto)\b", r"\besta errad[oa]\b", r"\bnao e (isso|esse)\b"],
    "objecao_preco": [
        r"\bcaro\b",
        r"\bsalgado\b",
        r"\bpreco (alto|ta alto)\b",
        r"\bmais barato\b",
        r"\bfranquia (ta )?alta\b",
        r"\bpreciso pensar\b",
        r"\bvou pensar\b",
    ],
    "concorrente": [
        r"\bporto seguro\b",
        r"\bazul\b",
        r"\bbradesco\b",
        r"\bsulamerica\b",
        r"\bitau\b",
        r"\bconcorrente\b",
        r"\bme ofereceu menos\b",
        r"\boutra seguradora\b",
    ],
    "pergunta_planos": [
        r"\bquais (sao os )?planos\b",
        r"\bque planos\b",
        r"\bdiferenca entre\b",
        r"\bo que (cobre|inclui)\b",
    ],
    "saudacao": [r"^(oi|ola|bom dia|boa tarde|boa noite|eae|e ai)\b"],
}
_MIDIA = re.compile(r"^\[(documento|imagem|audio|áudio|video)\]", re.IGNORECASE)


def parse_data(t: str, hoje: date) -> date | None:
    if m := _RE_DATA_ISO.search(t):
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    if m := _RE_DATA_BR.search(t):
        d, mes = int(m[1]), int(m[2])
        ano = int(m[3]) if m[3] else hoje.year
        ano = ano + 2000 if ano < 100 else ano
        try:
            dt = date(ano, mes, d)
        except ValueError:
            return None
        return dt if m[3] or dt >= hoje else date(ano + 1, mes, d)
    if re.search(r"\bhoje\b|\bimediato\b|\bagora\b|\bja\b", t):
        return hoje
    if re.search(r"\bamanha\b", t):
        return hoje + timedelta(days=1)
    if m := _RE_DIA.search(t):
        d = int(m[1])
        alvo = hoje.replace(day=1)
        for _ in range(2):
            try:
                cand = alvo.replace(day=d)
                if cand >= hoje:
                    return cand
            except ValueError:
                pass
            alvo = (alvo + timedelta(days=32)).replace(day=1)
    return None


class RuleExtractor:
    async def extract(self, text: str, awaiting: str | None, hoje: date) -> Extraction:
        t = _norm(text).strip()
        ex = Extraction()

        if _MIDIA.match(text.strip()):
            ex.intents.add("midia")
            return ex

        for intent, pats in _INTENTS.items():
            if any(re.search(p, t) for p in pats):
                ex.intents.add(intent)

        # data de início (antes do ano, para a data não virar ano do carro)
        data = parse_data(t, hoje)
        if data and (awaiting == "data_inicio" or re.search(r"\b(comec|inici|vigencia|a partir)", t)):
            ex.slots["data_inicio"] = data
        sem_datas = _RE_DATA_BR.sub(" ", _RE_DATA_ISO.sub(" ", t))

        # idade: só com marcador explícito de pessoa, ou número solto quando perguntamos a idade
        for pat in _RE_IDADE:
            if (m := pat.search(sem_datas)) and not re.search(
                r"\b(carro|veiculo|moto)\b[^.]*" + m.group(0), sem_datas
            ):
                ex.slots["idade"] = int(m[1])
                break
        if (
            "idade" not in ex.slots
            and awaiting == "idade"
            and (m := re.fullmatch(r"\D*(\d{2,3})\D*", sem_datas))
        ):
            ex.slots["idade"] = int(m[1])

        # ano do veículo: ano de 4 dígitos fora de datas, plausível
        anos = [int(a) for a in _RE_ANO.findall(sem_datas) if 1950 <= int(a) <= hoje.year + 1]
        if anos:
            ex.slots["veiculo_ano"] = anos[0]

        # CEP: token do guardrail (o valor real fica no vault) ou CEP generalizado da Gold
        if m := _RE_CEP_TOKEN.search(text):
            ex.slots["cep"] = m.group(0)

        # plano
        for pid, words in _PLANOS.items():
            if any(re.search(rf"\b{w}\b", t) for w in words):
                if not (pid == "essencial" and "objecao_preco" in ex.intents and awaiting != "plano_id"):
                    ex.slots["plano_id"] = pid
                    break

        if awaiting == "data_inicio" and "data_inicio" not in ex.slots and ex.intents & {"aceite"}:
            ex.slots["data_inicio"] = hoje  # "pode ser", "sim": começa hoje
        return ex
