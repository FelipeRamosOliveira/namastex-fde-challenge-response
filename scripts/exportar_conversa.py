"""Converte o transcript JSONL de uma sessão do Claude Code num Markdown legível para ai-logs/.

Inclui só o que aparece na tela: mensagens do usuário, texto das respostas do assistente e, de cada
ação, o nome da ferramenta e a descrição curta. Fica de fora: raciocínio interno, parâmetros e saídas
de ferramentas (onde ficariam comandos, conteúdo de arquivos e chaves), lembretes de sistema e
resumos automáticos de contexto. Segue só o ramo principal da conversa (sem subagentes).

Uso: uv run python scripts/exportar_conversa.py <sessao.jsonl> ai-logs/raw/<nome>.md
Depois: uv run python scripts/sanitize_ai_logs.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SISTEMA = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
BRT = timezone(timedelta(hours=-3))


def ramo_principal(entradas: list[dict]) -> list[dict]:
    por_uuid = {e["uuid"]: e for e in entradas if e.get("uuid")}
    msgs = [e for e in entradas if e.get("type") in ("user", "assistant") and not e.get("isSidechain")]
    folha = msgs[-1]
    cadeia = []
    while folha:
        cadeia.append(folha)
        pai = folha.get("parentUuid") or folha.get("logicalParentUuid")
        folha = por_uuid.get(pai)
    return [e for e in reversed(cadeia) if e.get("type") in ("user", "assistant")]


def hora(e: dict) -> str:
    ts = e.get("timestamp")
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(BRT).strftime("%H:%M") if ts else ""


def texto_usuario(e: dict) -> str | None:
    if e.get("isCompactSummary"):
        return "(resumo automático do contexto anterior, gerado pelo sistema: omitido)"
    c = e["message"]["content"]
    blocos = [c] if isinstance(c, str) else [b.get("text", "") for b in c if b.get("type") == "text"]
    t = SISTEMA.sub("", "\n".join(blocos)).strip()
    if not t or t.startswith(("[Image:", "Base directory for this skill", "Tool loaded")):
        return None
    return t


def main(src: str, dst: str) -> None:
    entradas = [
        json.loads(linha) for linha in Path(src).read_text(encoding="utf-8").splitlines() if linha.strip()
    ]
    out = ["# Sessão com Claude: desenvolvimento do AutoSeguro Agent", ""]
    bloco_assistente: list[str] = []
    acoes: list[str] = []

    def fechar():
        if acoes or bloco_assistente:
            out.append("**Claude**")
            out.append("")
            if acoes:
                out.append("Ações: " + " · ".join(acoes))
                out.append("")
            out.extend(bloco_assistente)
            out.append("")
        acoes.clear()
        bloco_assistente.clear()

    for e in ramo_principal(entradas):
        if e["type"] == "user":
            t = texto_usuario(e)
            if t is None:
                continue
            fechar()
            out += [f"### Felipe ({hora(e)})", "", t, ""]
            continue
        for b in e["message"].get("content", []):
            if b.get("type") == "text" and b["text"].strip():
                bloco_assistente.append(b["text"].strip())
                bloco_assistente.append("")
            elif b.get("type") == "tool_use":
                inp = b.get("input") or {}
                if b["name"] == "SendUserMessage":  # mensagem mostrada ao usuário
                    bloco_assistente += [inp.get("message", "").strip(), ""]
                    continue
                desc = inp.get("description")
                acoes.append(f"`{b['name']}`" + (f" ({desc})" if desc and len(desc) < 80 else ""))
    fechar()
    Path(dst).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"{dst}: {sum(1 for x in out if x.startswith('### Felipe'))} mensagens do usuário")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
