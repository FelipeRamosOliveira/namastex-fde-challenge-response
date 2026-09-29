"""Guardrail de PII: detecta e mascara dados pessoais com tokens estáveis por conversa.

Regra de ouro: nenhum texto chega a LLM, log ou trace sem passar por `mask`.
O valor original fica só no `PiiVault` da conversa (usado quando a cotação
precisa do CEP, por exemplo). Na dúvida, mascara: falso positivo custa pouco,
vazamento custa caro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class PiiKind(StrEnum):
    CPF = "CPF"
    EMAIL = "EMAIL"
    TELEFONE = "TELEFONE"
    PLACA = "PLACA"
    CEP = "CEP"
    NOME = "NOME"


# Ordem importa: padrões mais específicos primeiro, para um número não ser
# capturado por dois tipos ao mesmo tempo.
_PATTERNS: list[tuple[PiiKind, re.Pattern[str]]] = [
    (PiiKind.EMAIL, re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # CPF: 000.000.000-00, 00000000000, 000 000 000 00
    (PiiKind.CPF, re.compile(r"(?<!\d)\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}(?!\d)")),
    # Telefone BR: +55, DDD opcional (com ou sem parênteses), celular 9xxxx-xxxx ou fixo xxxx-xxxx com DDD
    (
        PiiKind.TELEFONE,
        re.compile(
            r"(?<![\w-])(?:\+?55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)?9\d{4}[\s-]?\d{4}(?!\d)"
            r"|(?<![\w-])(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?[2-5]\d{3}[\s-]?\d{4}(?!\d)"
        ),
    ),
    # Placa: antiga ABC-1234 / ABC1234 e Mercosul ABC1D23
    (PiiKind.PLACA, re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}-?\d[A-Za-z0-9]\d{2}(?![A-Za-z0-9])")),
    # CEP: 00000-000 ou 00000000
    (PiiKind.CEP, re.compile(r"(?<!\d)\d{5}-?\d{3}(?!\d)")),
]

_TOKEN_RE = re.compile(r"\[(CPF|EMAIL|TELEFONE|PLACA|CEP|NOME)_\d+\]")


def cpf_valido(cpf: str) -> bool:
    """Valida os dígitos verificadores de um CPF (aceita com ou sem pontuação)."""
    d = [int(c) for c in cpf if c.isdigit()]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(v * (n + 1 - i) for i, v in enumerate(d[:n]))
        dv = (s * 10) % 11 % 10
        if dv != d[n]:
            return False
    return True


@dataclass
class Entity:
    kind: PiiKind
    value: str
    start: int
    end: int


@dataclass
class PiiVault:
    """Mapa token -> valor original, por conversa. Mesmo valor recebe o mesmo token."""

    tokens: dict[str, str] = field(default_factory=dict)

    def token_for(self, kind: PiiKind, value: str) -> str:
        norm = _normalize(kind, value)
        for tok, val in self.tokens.items():
            if tok.startswith(f"[{kind}_") and _normalize(kind, val) == norm:
                return tok
        n = sum(1 for t in self.tokens if t.startswith(f"[{kind}_")) + 1
        tok = f"[{kind}_{n}]"
        self.tokens[tok] = value
        return tok

    def reveal(self, token: str) -> str | None:
        return self.tokens.get(token)

    def latest(self, kind: PiiKind) -> str | None:
        vals = [v for t, v in self.tokens.items() if t.startswith(f"[{kind}_")]
        return vals[-1] if vals else None

    def to_dict(self) -> dict[str, str]:
        return dict(self.tokens)

    @classmethod
    def from_dict(cls, data: dict[str, str] | None) -> PiiVault:
        return cls(tokens=dict(data or {}))


def _normalize(kind: PiiKind, value: str) -> str:
    if kind in (PiiKind.EMAIL, PiiKind.PLACA, PiiKind.NOME):
        return value.lower().replace("-", "").strip()
    return re.sub(r"\D", "", value)


def scan(text: str, names: list[str] | None = None) -> list[Entity]:
    """Encontra entidades de PII sem sobreposição (a primeira regra que casa vence)."""
    taken: list[tuple[int, int]] = []
    found: list[Entity] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            if _TOKEN_RE.fullmatch(m.group(0)) or not free(m.start(), m.end()):
                continue
            # 11 dígitos sem pontuação que não é CPF válido pode ser telefone: deixa para a regra seguinte
            if kind is PiiKind.CPF and not re.search(r"[.\-\s]", m.group(0)) and not cpf_valido(m.group(0)):
                continue
            taken.append((m.start(), m.end()))
            found.append(Entity(kind, m.group(0), m.start(), m.end()))

    for name in names or []:
        for part in {p for p in name.split() if len(p) >= 3}:
            for m in re.finditer(rf"(?<!\w){re.escape(part)}(?!\w)", text, flags=re.IGNORECASE):
                if free(m.start(), m.end()):
                    taken.append((m.start(), m.end()))
                    found.append(Entity(PiiKind.NOME, m.group(0), m.start(), m.end()))
    return sorted(found, key=lambda e: e.start)


@dataclass
class MaskResult:
    text: str
    entities: list[Entity]


def mask(text: str, vault: PiiVault | None = None, names: list[str] | None = None) -> MaskResult:
    """Troca cada entidade por um token estável. Sem vault, usa um vault descartável."""
    vault = vault if vault is not None else PiiVault()
    ents = scan(text, names=names)
    out, last = [], 0
    for e in ents:
        out.append(text[last : e.start])
        out.append(vault.token_for(e.kind, e.value))
        last = e.end
    out.append(text[last:])
    return MaskResult(text="".join(out), entities=ents)


def contains_pii(text: str, names: list[str] | None = None) -> bool:
    return bool(scan(text, names=names))


def mask_dict(data: object, vault: PiiVault | None = None) -> object:
    """Mascara recursivamente strings em dicts e listas (para logs e traces)."""
    if isinstance(data, str):
        return mask(data, vault).text
    if isinstance(data, dict):
        return {k: mask_dict(v, vault) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask_dict(v, vault) for v in data]
    return data
