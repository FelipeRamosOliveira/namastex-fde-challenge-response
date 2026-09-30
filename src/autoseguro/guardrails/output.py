"""Guardrail de saída: nenhuma resposta ao lead sai com PII ou com valor em R$ que não veio da API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from autoseguro.guardrails.pii import scan

_RE_BRL = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?|R\$\s?\d+(?:,\d{2})?")
_RE_TOKEN = re.compile(r"\[(CPF|EMAIL|TELEFONE|PLACA|CEP|NOME|CNPJ|RG|CARTAO)_\d+\]")


@dataclass
class OutputCheck:
    ok: bool
    violacoes: list[str] = field(default_factory=list)


def _canon(v: str) -> str:
    v = v.replace("R$", "").strip()
    if "," not in v:
        v += ",00"
    return "R$ " + v


def check_output(text: str, valores_permitidos: set[str]) -> OutputCheck:
    viol: list[str] = []
    for e in scan(text):
        viol.append(f"pii:{e.kind}")
    if _RE_TOKEN.search(text):
        viol.append("pii:token_exposto")
    permitidos = {_canon(v) for v in valores_permitidos}
    for m in _RE_BRL.finditer(text):
        if _canon(m.group(0)) not in permitidos:
            viol.append(f"valor_nao_verificado:{m.group(0)}")
    return OutputCheck(ok=not viol, violacoes=viol)
