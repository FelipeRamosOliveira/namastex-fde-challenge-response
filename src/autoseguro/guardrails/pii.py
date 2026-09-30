"""Guardrail de PII: detecta e mascara dados pessoais com tokens estáveis por conversa.

Regra de ouro: nenhum texto chega a LLM, log, trace, fila ou checkpoint sem passar
por `mask`. Na dúvida, mascara: falso positivo custa pouco, vazamento custa caro.

Minimização: o `PiiVault` guarda o valor original SÓ do que o negócio precisa usar
(o CEP, enviado à /quote). Os demais tipos ficam como hash, o suficiente para dar o
mesmo token ao mesmo valor e reconhecer um nome já dito, sem reter o dado.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class PiiKind(StrEnum):
    CPF = "CPF"
    EMAIL = "EMAIL"
    TELEFONE = "TELEFONE"
    PLACA = "PLACA"
    CEP = "CEP"
    NOME = "NOME"
    CNPJ = "CNPJ"
    RG = "RG"
    CARTAO = "CARTAO"


RETER_ORIGINAL = {PiiKind.CEP}  # únicos originais guardados no vault

# Criptografia do original retido (Fernet). Configurada na subida via VAULT_KEY.
# VAULT_KEY aceita várias chaves separadas por vírgula (rotação): a primeira cifra,
# todas servem para abrir. Dado cifrado com chave que não está mais na lista fica ilegível
# (tratado como ausente: o agente pede o dado de novo), nunca derruba a conversa.
_cipher = None


def configurar_chave_vault(chave: str | None) -> None:
    global _cipher
    if chave:
        from cryptography.fernet import Fernet, MultiFernet

        _cipher = MultiFernet([Fernet(k.strip().encode()) for k in chave.split(",") if k.strip()])
    else:
        _cipher = None


def cifrar_texto(valor: str) -> str:
    """Cifra um valor sensível para guardar (sem chave, fica em claro: só desenvolvimento)."""
    return "enc:" + _cipher.encrypt(valor.encode()).decode() if _cipher else valor


def abrir_texto(valor: str) -> str | None:
    """Abre o que `cifrar_texto` gravou. None se ilegível (sem chave ou chave rotacionada)."""
    if valor.startswith("h:"):
        return None
    if valor.startswith("enc:"):
        if _cipher is None:
            return None
        from cryptography.fernet import InvalidToken

        try:
            return _cipher.decrypt(valor[4:].encode()).decode()
        except InvalidToken:
            return None
    return valor


_cifrar = cifrar_texto
_abrir = abrir_texto

# Pseudônimos (id da conversa, hashes do vault). Com PSEUDONIMO_KEY: HMAC-SHA256 com esse segredo;
# sem ela, SHA-256 puro (compatível com as conversas já gravadas). Auditoria: telefone e CPF têm
# espaço pequeno e o SHA-256 sem chave pode ser revertido por força bruta; é pseudonimização,
# não anonimização. Trocar a chave muda os ids: conversas antigas não são encontradas.
_chave_pseudonimo: bytes | None = None


def configurar_chave_pseudonimo(chave: str | None) -> None:
    global _chave_pseudonimo
    _chave_pseudonimo = chave.encode() if chave else None


def pseudonimo(valor: str) -> str:
    """Hash hexadecimal de um identificador: HMAC quando há chave configurada."""
    if _chave_pseudonimo:
        return hmac.new(_chave_pseudonimo, valor.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(valor.encode()).hexdigest()


_SEP = r"[\s.-]?"
# Ordem importa: padrões mais específicos primeiro, para um número não ser capturado duas vezes.
_PATTERNS: list[tuple[PiiKind, re.Pattern[str]]] = [
    (PiiKind.EMAIL, re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # CNPJ: 00.000.000/0000-00 ou 14 dígitos corridos (antes do CPF e do telefone)
    (PiiKind.CNPJ, re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")),
    # CPF pontuado: 000.000.000-00 / 000 000 000 00 (11 dígitos corridos: ver _NUM_LONGO)
    (PiiKind.CPF, re.compile(r"(?<!\d)\d{3}[.\s]\d{3}[.\s]\d{3}[-.\s]\d{2}(?!\d)")),
    # Celular: +55, DDD opcional (com/sem parênteses), 9 separado ou não: 9 7224-2584, 97224 2584
    (
        PiiKind.TELEFONE,
        re.compile(rf"(?<![\w-])(?:\+?55{_SEP})?(?:\(?\d{{2}}\)?{_SEP})?9{_SEP}\d{{4}}{_SEP}\d{{4}}(?!\d)"),
    ),
    # Fixo com DDD, ou fixo sem DDD com hífen (3333-4444)
    (
        PiiKind.TELEFONE,
        re.compile(
            rf"(?<![\w-])(?:\+?55{_SEP})?\(?\d{{2}}\)?{_SEP}[2-5]\d{{3}}{_SEP}\d{{4}}(?!\d)"
            r"|(?<![\w-])[2-5]\d{3}-\d{4}(?![\d-])"
        ),
    ),
    # Placa: antiga ABC-1234 / ABC1234 e Mercosul ABC1D23
    (PiiKind.PLACA, re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}-?\d[A-Za-z0-9]\d{2}(?![A-Za-z0-9])")),
    # CEP: 00000-000, 00000000 e as variações com outro separador (00000 000, 00.000-000, 00000.000)
    (PiiKind.CEP, re.compile(r"(?<![\d.])\d{2}\.?\d{3}[-\s.]?\d{3}(?!\d|[.,]\d)")),
]
# RG: só com a palavra antes ("rg 12.345.678-9", "RG: 123456789"); o número sozinho é ambíguo
_RG = re.compile(
    r"\b(?:rg|identidade)\b\s*(?:n[º°o.]*\s*)?[:\s]\s*(\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX])(?!\d)", re.IGNORECASE
)
# Cartão: grupos de 4 com o mesmo separador (espaço, hífen ou nenhum) ou Amex 4-6-5; confirmado pelo
# Luhn. Sem grupo fixo, ids como "sim-conv_01185-1790708560324" passavam no Luhn por acaso.
_CARTAO = re.compile(
    r"(?<![\w.-])(?:\d{4}([ -]?)\d{4}\1\d{4}\1\d{1,7}|\d{4}([ -]?)\d{6}\2\d{5})(?![\w-]|[.,]\d)"
)
# 10 ou 11 dígitos corridos que sobraram: CPF (mesmo com dígito inválido) ou telefone
_NUM_LONGO = re.compile(r"(?<!\d)\d{10,11}(?!\d)")
# Nome declarado: "meu nome é Ana Souza", "me chamo ana", "sou a Ana Souza" (com maiúscula)
# Sobrenome depois de "da", "de", "do", "dos", "das" também entra ("Ana da Silva", "João de Souza")
_CONECTOR = r"(?:\s+d[aeo]s?\s+[A-Za-zÀ-ÿ]{2,})"
_NAO_CONECTOR = r"(?!d[aeo]s?\b)"  # o segundo nome não pode ser o "da" do sobrenome
_NOME_DECL = re.compile(
    rf"(?:meu nome (?:é|e|eh)|me chamo)\s+"
    rf"([A-Za-zÀ-ÿ]{{2,}}(?:\s+{_NAO_CONECTOR}[A-Za-zÀ-ÿ]{{2,}})?{_CONECTOR}*)"
    rf"|(?:\bsou (?:o|a))\s+([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+{_NAO_CONECTOR}[A-ZÀ-Ý][a-zà-ÿ]+)?{_CONECTOR}*)",
    re.IGNORECASE,
)
_NAO_NOME = {
    "de",
    "da",
    "do",
    "dos",
    "das",
    "e",
    "cliente",
    "interessado",
    "interessada",
    "dono",
    "dona",
    "seu",
    "sua",
}
_TOKEN_RE = re.compile(r"\[(CPF|EMAIL|TELEFONE|PLACA|CEP|NOME|CNPJ|RG|CARTAO)_\d+\]")
# Ids gerados pelo próprio sistema (hex): não são PII, mas têm sequências de dígitos
_ID_INTERNO = re.compile(r"\b(?:evt|msg|qr|q|ho|out|sys|conv|omni|sim)_[0-9a-f]{6,}\b")


def cpf_valido(cpf: str) -> bool:
    """Valida os dígitos verificadores de um CPF (aceita com ou sem pontuação)."""
    d = [int(c) for c in cpf if c.isdigit()]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(v * (n + 1 - i) for i, v in enumerate(d[:n]))
        if (s * 10) % 11 % 10 != d[n]:
            return False
    return True


def luhn_valido(numero: str) -> bool:
    """Dígito verificador de cartão (Luhn)."""
    d = [int(c) for c in numero if c.isdigit()]
    if not 13 <= len(d) <= 19 or len(set(d)) == 1:
        return False
    soma = 0
    for i, v in enumerate(reversed(d)):
        if i % 2:
            v = v * 2 - 9 if v > 4 else v * 2
        soma += v
    return soma % 10 == 0


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _normalize(kind: PiiKind, value: str) -> str:
    if kind in (PiiKind.EMAIL, PiiKind.PLACA, PiiKind.NOME):
        return _fold(value).replace("-", "")
    return re.sub(r"\D", "", value)


def _h(s: str) -> str:
    return "h:" + pseudonimo(s)[:20]


@dataclass
class Entity:
    kind: PiiKind
    value: str
    start: int
    end: int


@dataclass
class PiiVault:
    """Token -> original (só CEP) ou hash do valor normalizado (demais tipos)."""

    tokens: dict[str, str] = field(default_factory=dict)

    def _stored(self, kind: PiiKind, value: str) -> str:
        return _cifrar(value) if kind in RETER_ORIGINAL else _h(_normalize(kind, value))

    def token_for(self, kind: PiiKind, value: str) -> str:
        alvo = _h(_normalize(kind, value))
        for tok, val in self.tokens.items():
            if tok.startswith(f"[{kind}_"):
                aberto = _abrir(val)
                cmp = val if val.startswith("h:") else (_h(_normalize(kind, aberto)) if aberto else None)
                if cmp == alvo:
                    return tok
        n = sum(1 for t in self.tokens if t.startswith(f"[{kind}_")) + 1
        tok = f"[{kind}_{n}]"
        self.tokens[tok] = self._stored(kind, value)
        return tok

    def reveal(self, token: str) -> str | None:
        v = self.tokens.get(token)
        return None if v is None else _abrir(v)

    def latest(self, kind: PiiKind) -> str | None:
        vals = [_abrir(v) for t, v in self.tokens.items() if t.startswith(f"[{kind}_")]
        vals = [v for v in vals if v]
        return vals[-1] if vals else None

    def name_hashes(self) -> dict[str, str]:
        """hash da parte do nome -> token, para reconhecer o nome em mensagens seguintes."""
        return {v: t for t, v in self.tokens.items() if t.startswith("[NOME_")}

    def to_dict(self) -> dict[str, str]:
        return dict(self.tokens)

    @classmethod
    def from_dict(cls, data: dict[str, str] | None) -> PiiVault:
        return cls(tokens=dict(data or {}))


def scan(text: str, names: list[str] | None = None, vault: PiiVault | None = None) -> list[Entity]:
    """Encontra entidades de PII sem sobreposição (a primeira regra que casa vence)."""
    taken: list[tuple[int, int]] = []
    found: list[Entity] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    def add(kind: PiiKind, a: int, b: int) -> None:
        taken.append((a, b))
        found.append(Entity(kind, text[a:b], a, b))

    for m in _TOKEN_RE.finditer(text):  # tokens já mascarados não são tocados
        taken.append((m.start(), m.end()))
    for m in _ID_INTERNO.finditer(text):
        taken.append((m.start(), m.end()))
    for m in _CARTAO.finditer(text):  # cartão (Luhn) antes de CPF, CNPJ e telefone
        digitos = re.sub(r"\D", "", m.group(0))
        if free(m.start(), m.end()) and len(digitos) != 14 and luhn_valido(digitos):
            add(PiiKind.CARTAO, m.start(), m.end())
    for m in _RG.finditer(text):
        if free(m.start(1), m.end(1)):
            add(PiiKind.RG, m.start(1), m.end(1))
    for m in _NUM_LONGO.finditer(text):  # CPF válido sem pontuação vence o padrão de celular
        if free(m.start(), m.end()) and len(m.group(0)) == 11 and cpf_valido(m.group(0)):
            add(PiiKind.CPF, m.start(), m.end())
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            if free(m.start(), m.end()):
                add(kind, m.start(), m.end())
    for m in _NUM_LONGO.finditer(text):
        if free(m.start(), m.end()):
            dig = m.group(0)
            add(
                PiiKind.CPF if len(dig) == 11 and (cpf_valido(dig) or dig[2] != "9") else PiiKind.TELEFONE,
                m.start(),
                m.end(),
            )

    partes_nome: set[str] = set()
    for name in names or []:
        partes_nome |= {p for p in name.split() if len(p) >= 3}
    for m in _NOME_DECL.finditer(text):
        grupo = 1 if m.group(1) else 2
        palavras = [p for p in m.group(grupo).split() if _fold(p) not in _NAO_NOME]
        for p in palavras:
            partes_nome.add(p)
    for part in partes_nome:
        for m in re.finditer(rf"(?<!\w){re.escape(part)}(?!\w)", text, flags=re.IGNORECASE):
            if free(m.start(), m.end()):
                add(PiiKind.NOME, m.start(), m.end())
    if vault is not None:  # nomes ditos antes nesta conversa (comparação por hash)
        conhecidos = vault.name_hashes()
        if conhecidos:
            for m in re.finditer(r"[A-Za-zÀ-ÿ]{3,}", text):
                if free(m.start(), m.end()) and _h(_normalize(PiiKind.NOME, m.group(0))) in conhecidos:
                    add(PiiKind.NOME, m.start(), m.end())
    return sorted(found, key=lambda e: e.start)


@dataclass
class MaskResult:
    text: str
    entities: list[Entity]


def mask(text: str, vault: PiiVault | None = None, names: list[str] | None = None) -> MaskResult:
    """Troca cada entidade por um token estável. Sem vault, usa um vault descartável."""
    vault = vault if vault is not None else PiiVault()
    ents = scan(text, names=names, vault=vault)
    out, last = [], 0
    for e in ents:
        out.append(text[last : e.start])
        out.append(vault.token_for(e.kind, e.value))
        last = e.end
    out.append(text[last:])
    return MaskResult(text="".join(out), entities=ents)


def nomes_conhecidos(text: str, vault: PiiVault) -> list[str]:
    """Palavras do texto que são um nome já dito nesta conversa (comparação por hash)."""
    conhecidos = vault.name_hashes()
    return [
        m.group(0)
        for m in re.finditer(r"[A-Za-zÀ-ÿ]{3,}", text)
        if _h(_normalize(PiiKind.NOME, m.group(0))) in conhecidos
    ]


def contains_pii(text: str, names: list[str] | None = None) -> bool:
    return bool(scan(text, names=names))


_ID_KEYS = re.compile(r"(^|_)(id|ref)$")


def mask_dict(data: object, vault: PiiVault | None = None, _key: str = "") -> object:
    """Mascara recursivamente strings em dicts e listas. Chaves de id (`*_id`, `*_ref`) são opacas
    por construção e não são alteradas, para não quebrar o roteamento."""
    if isinstance(data, str):
        return data if _ID_KEYS.search(_key) else mask(data, vault).text
    if isinstance(data, dict):
        return {k: mask_dict(v, vault, k) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask_dict(v, vault, _key) for v in data]
    return data
