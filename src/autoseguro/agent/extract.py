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
    fonte: str = "regras"  # regras | llm:<provedor>
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
# "anos de carteira", "anos de casado": número de anos que não é a idade do condutor
_RE_ANOS_DE_OUTRA_COISA = re.compile(
    r"\d{1,3} anos (de|como) "
    r"(carteira|habilitacao|cnh|casad|empresa|experiencia|motorista|direcao|uso|garantia)"
)
# "carro tem 12 anos", "veiculo com 8 anos": idade do carro, não do condutor
_RE_IDADE_DO_CARRO = re.compile(r"\b(carro|veiculo|moto|ele)\b\s+(tem|com|de)\s+(\d{1,2}) anos")
# ano que não é do carro: "nasci em 1985", "desde 2010", "habilitado em 2005"
_RE_ANO_NAO_CARRO = re.compile(r"\b(nasci|nascido|nascida|desde|habilitad[oa]|carteira|cnh)\b[^.,;]{0,12}$")
IDADE_MIN, IDADE_MAX = 16, 110

# números por extenso (texto normalizado): só de 10 a 100, porque "um"/"uma" são artigos
# ("um hb20") e idade abaixo de 16 não interessa. Teste ao vivo: "tenho trinta e dois".
_UNIDADES = {
    "um": 1,
    "dois": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
_DEZENAS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
_RE_EXTENSO = re.compile(
    rf"\b(?:({'|'.join(_DEZENAS)})(?: e ({'|'.join(_UNIDADES)}))?|({'|'.join(_DEZ_A_DEZENOVE)})|(cem))\b"
)


def extenso_para_digitos(t: str) -> str:
    """ "tenho trinta e dois" -> "tenho 32" (espera texto já normalizado por `_norm`)."""

    def troca(m: re.Match[str]) -> str:
        if m[1]:
            return str(_DEZENAS[m[1]] + (_UNIDADES[m[2]] if m[2] else 0))
        return str(_DEZ_A_DEZENOVE[m[3]]) if m[3] else "100"

    return _RE_EXTENSO.sub(troca, t)


def numeros_no_texto(text: str) -> set[str]:
    """Números que o lead escreveu, em dígitos ou por extenso."""
    return set(re.findall(r"\d+", text)) | set(re.findall(r"\d+", extenso_para_digitos(_norm(text))))


# dia da semana ("segunda que vem"); "segunda via" é outro assunto. Teste ao vivo: numa quarta,
# o LLM leu "a partir de segunda que vem" como a sexta seguinte.
_DIAS_SEMANA = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
_RE_DIA_SEMANA = re.compile(
    r"\b(segunda(?! (?:via|opcao|vez|mao))|terca|quarta|quinta|sexta)(?:[- ]feira)?\b|\b(sabado|domingo)\b"
)
# ano do carro dito sem número; "comprei ano passado" é data da compra, não ano do modelo
_RE_ANO_RELATIVO = re.compile(
    r"\b(zero km|0 ?km|ano retrasado|ano passado|deste ano|desse ano|este ano|esse ano)\b"
)
_RE_COMPRA = re.compile(r"\b(comprei|compramos|peguei|adquiri|troquei)\b")

MARCAS = {
    "volkswagen",
    "vw",
    "chevrolet",
    "gm",
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
    "kia",
    "mitsubishi",
    "caoa",
    "chery",
    "bmw",
    "audi",
    "mercedes",
}
MODELOS = {
    "gol",
    "polo",
    "virtus",
    "t-cross",
    "nivus",
    "fox",
    "up",
    "voyage",
    "saveiro",
    "jetta",
    "onix",
    "tracker",
    "spin",
    "prisma",
    "celta",
    "cruze",
    "s10",
    "argo",
    "mobi",
    "cronos",
    "pulse",
    "toro",
    "uno",
    "palio",
    "strada",
    "siena",
    "hb20",
    "creta",
    "corolla",
    "yaris",
    "etios",
    "hilux",
    "civic",
    "city",
    "hr-v",
    "fit",
    "renegade",
    "compass",
    "kwid",
    "sandero",
    "duster",
    "logan",
    "ka",
    "fiesta",
    "ecosport",
    "kicks",
    "versa",
    "sentra",
    "tiggo",
}
_RE_MODELO = re.compile(r"\b(" + "|".join(re.escape(w) for w in MARCAS | MODELOS) + r")\b")


def menciona_modelo(text: str) -> bool:
    """O lead já disse a marca ou o modelo ("quero cotar meu hb20")."""
    return bool(_RE_MODELO.search(_norm(text)))


_RE_PALAVRA_CARRO = re.compile(
    r"\b(carro|veiculo|modelo|ano|automovel|" + "|".join(re.escape(w) for w in MARCAS | MODELOS) + r")\b"
)

# ordem importa: frases do premium antes de "completo"
_PLANOS = {
    "premium": ["premium", "mais completo", "top de linha", "o melhor"],
    "essencial": ["essencial", "basico", "mais barato", "mais em conta"],
    "completo": ["completo"],
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
        # "prefiro ver outro" depois da cotação é outro plano, não outra seguradora
        r"\b(ver|cotar|mostrar|mostra|quero|prefiro) (o )?(outro|outra|outros|outras)\b",
        r"\boutr[oa]s? (plano|planos|opcao|opcoes)\b",
    ],
    "saudacao": [r"^(oi|ola|bom dia|boa tarde|boa noite|eae|e ai)\b"],
}
_MIDIA = re.compile(r"^\[(documento|document|imagem|image|audio|áudio|video|sticker)\]", re.IGNORECASE)


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
    if m := _RE_DIA_SEMANA.search(t):
        alvo = _DIAS_SEMANA[m[1] or m[2]]
        if re.search(r"\b(semana que vem|proxima semana)\b", t):  # "sexta da semana que vem"
            return hoje + timedelta(days=7 - hoje.weekday() + alvo)
        return hoje + timedelta(days=(alvo - hoje.weekday()) % 7 or 7)  # próxima, nunca hoje
    if re.search(r"\b(semana que vem|proxima semana)\b", t):
        return hoje + timedelta(days=7)
    if re.search(r"\b(mes que vem|proximo mes)\b", t):
        return (hoje.replace(day=1) + timedelta(days=32)).replace(day=1)
    if re.search(r"\bdepois de amanha\b", t):
        return hoje + timedelta(days=2)
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
        t = extenso_para_digitos(_norm(text).strip())
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

        # idade: marcador explícito de pessoa, ou número solto quando perguntamos a idade.
        # Números que são idade do carro ou "anos de carteira" ficam de fora.
        excluidos = [m.span(3) for m in _RE_IDADE_DO_CARRO.finditer(sem_datas)]
        excluidos += [m.span() for m in _RE_ANOS_DE_OUTRA_COISA.finditer(sem_datas)]

        def fora(span: tuple[int, int]) -> bool:
            return not any(a <= span[0] < b for a, b in excluidos)

        idade = None
        for pat in _RE_IDADE:
            for m in pat.finditer(sem_datas):
                if fora(m.span(1)):
                    idade = int(m[1])
                    break
            if idade is not None:
                break
        if (
            idade is None
            and awaiting == "idade"
            and (m := re.fullmatch(r"\D*?(\d{2,3})(?: anos)?\D*", sem_datas))
        ):
            if fora(m.span(1)) and not _RE_ANOS_DE_OUTRA_COISA.search(sem_datas):
                idade = int(m[1])
        if idade is not None and IDADE_MIN <= idade <= IDADE_MAX:
            ex.slots["idade"] = idade

        # ano do veículo: 4 dígitos fora de datas, plausível, com contexto de carro
        # (ou quando perguntamos o carro), e nunca depois de "nasci", "desde"...
        for m in _RE_ANO.finditer(sem_datas):
            ano = int(m[1])
            antes = sem_datas[: m.start()]
            if not (1950 <= ano <= hoje.year + 1) or _RE_ANO_NAO_CARRO.search(antes):
                continue
            if awaiting == "veiculo_ano" or _RE_PALAVRA_CARRO.search(sem_datas):
                ex.slots["veiculo_ano"] = ano
                break
        # sem número: "é do ano passado", "zero km"; só com contexto claro de ano do carro
        if "veiculo_ano" not in ex.slots and (m := _RE_ANO_RELATIVO.search(sem_datas)):
            antes = sem_datas[: m.start()]
            zero_km = m[1].startswith(("zero", "0"))
            contexto = (
                awaiting == "veiculo_ano"
                or re.search(r"\b(e|eh|modelo) (do|de) $", antes)
                or (zero_km and _RE_PALAVRA_CARRO.search(sem_datas))
            )
            if contexto and not _RE_COMPRA.search(antes):
                recuo = 2 if m[1] == "ano retrasado" else 1 if m[1] == "ano passado" else 0
                ex.slots["veiculo_ano"] = hoje.year - recuo

        # CEP: token do guardrail (o valor real fica no vault). Com dois, vale o último
        # ("moro no X mas o carro dorme no Y"); a confirmação mostra a região ao lead.
        if ceps := _RE_CEP_TOKEN.findall(text):
            ex.slots["cep"] = ceps[-1]

        # plano: palavra-chave explícita, ignorando a negada ("o mais barato não serve")
        def citado(w: str) -> bool:
            for m in re.finditer(rf"\b{w}\b", t):
                perto = t[max(0, m.start() - 12) : m.start()] + " " + t[m.end() : m.end() + 14]
                if not re.search(r"\bnao\b|\bnem\b", perto):
                    return True
            return False

        for pid, words in _PLANOS.items():
            if any(citado(w) for w in words):
                if not (pid == "essencial" and "objecao_preco" in ex.intents and awaiting != "plano_id"):
                    ex.slots["plano_id"] = pid
                    break

        sem_referencia_de_tempo = not re.search(
            r"semana|mes|dia|amanha|proxim|segunda|terca|quarta|quinta|sexta|sabado|domingo|depois", t
        )
        if (
            awaiting == "data_inicio"
            and "data_inicio" not in ex.slots
            and ex.intents & {"aceite"}
            and sem_referencia_de_tempo
        ):
            ex.slots["data_inicio"] = hoje  # "pode ser", "sim": começa hoje
        return ex
