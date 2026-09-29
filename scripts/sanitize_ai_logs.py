"""Sanitiza os exports das conversas com IA antes de ir para o repo público.

Fluxo:
  1. Copie os exports brutos para ai-logs/raw/ (ignorado pelo git).
     Claude Code: ~/.claude/projects/<slug>/*.jsonl
  2. uv run python scripts/sanitize_ai_logs.py
     -> grava em ai-logs/sessions/ com segredos e PII mascarados.
     (opcional: --valores-de .env remove também os valores literais do seu .env)
  3. uv run python scripts/sanitize_ai_logs.py --check
     -> falha se sobrou algo em ai-logs/ (usado no pre-commit e na CI).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoseguro.guardrails.pii import mask, scan  # noqa: E402

RAW = ROOT / "ai-logs" / "raw"
OUT = ROOT / "ai-logs" / "sessions"
CHECK_DIRS = [ROOT / "ai-logs", ROOT / "docs"]

SEGREDOS = [
    ("groq", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("openrouter", re.compile(r"sk-or-[A-Za-z0-9-]{20,}")),
    ("openai_anthropic", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}")),
    # chave em header ou objeto: 'x-api-key': '...', x-channel-key: ..., "authorization": "..."
    (
        "header",
        re.compile(
            r"(?i)(?:x-api-key|x-channel-key|api[_-]?key|authorization)['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?[A-Za-z0-9._~+/-]{20,}=*"
        ),
    ),
    ("fernet", re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}=(?![A-Za-z0-9_=-])")),
    ("env_kv", re.compile(r"(?i)\b([A-Z_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))\s*[=:]\s*['\"]?([^\s'\"]{8,})")),
]
# Valores sintéticos do dataset e exemplos do desafio podem aparecer nos logs: mascarar também.
IGNORAR_ARQUIVOS = {"README.md"}


LITERAIS: list[str] = []  # valores de um .env passado em --valores-de (nunca versionado)


def carregar_literais(env: Path) -> None:
    for linha in env.read_text(encoding="utf-8").splitlines():
        k, _, v = linha.partition("=")
        v = v.strip().strip("'\"")
        if k.strip() and not k.lstrip().startswith("#") and len(v) >= 8:
            LITERAIS.append(v)


def limpar(texto: str) -> str:
    for v in LITERAIS:
        texto = texto.replace(v, "[REDACTED_ENV]")
    for nome, pat in SEGREDOS:
        if nome == "env_kv":
            texto = pat.sub(lambda m: f"{m.group(1)}=[REDACTED]", texto)
        else:
            texto = pat.sub(f"[REDACTED_{nome.upper()}]", texto)
    return mask(texto).text


def achados(texto: str) -> list[str]:
    out = [nome for nome, pat in SEGREDOS if nome != "env_kv" and pat.search(texto)]
    out += ["env_literal" for v in LITERAIS if v in texto]
    out += [f"pii:{e.kind}" for e in scan(texto)]
    return out


def sanitize() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(RAW.rglob("*")) if RAW.exists() else []:
        if f.is_file() and f.suffix in {".jsonl", ".json", ".md", ".txt"}:
            dest = OUT / f.relative_to(RAW)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(limpar(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            n += 1
    print(f"{n} arquivo(s) sanitizados em {OUT.relative_to(ROOT)}")
    return 0


def check() -> int:
    problemas = []
    for base in CHECK_DIRS:
        for f in base.rglob("*"):
            if not f.is_file() or RAW in f.parents or f.name in IGNORAR_ARQUIVOS:
                continue
            if f.suffix not in {".jsonl", ".json", ".md", ".txt"}:
                continue
            a = achados(f.read_text(encoding="utf-8", errors="replace"))
            if a:
                problemas.append(f"{f.relative_to(ROOT)}: {sorted(set(a))}")
    for p in problemas:
        print(p)
    return 1 if problemas else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--valores-de", type=Path, help="um .env: seus valores literais também são removidos")
    a = ap.parse_args()
    if a.valores_de:
        carregar_literais(a.valores_de)
    sys.exit(check() if a.check else sanitize())
