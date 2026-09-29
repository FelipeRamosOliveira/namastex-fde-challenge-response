"""Cliente de LLM gratuito (API compatível com OpenAI): Groq principal, OpenRouter reserva.

Garantias:
- Bloqueio de PII: se qualquer mensagem enviada tiver PII detectável, a chamada NEM SAI
  (`PiiBloqueada`). O texto já chega mascarado; isto é defesa em profundidade.
- Cache exato (KVStore) por provedor+modelo+mensagens+schema: a mesma pergunta não gasta cota.
- Timeout curto e troca de provedor em erro, 429 ou resposta inválida.
- Nunca propaga exceção de rede: devolve `LLMIndisponivel` para o chamador cair nas regras.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from autoseguro.config import Settings
from autoseguro.guardrails.pii import scan
from autoseguro.tools.store import KVStore

CACHE_TTL_S = 7 * 24 * 3600


class LLMIndisponivel(Exception):
    pass


class PiiBloqueada(Exception):
    pass


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    json_schema: bool = True  # structured outputs estrito (gpt-oss no Groq)
    extra: dict[str, Any] = field(default_factory=dict)


def providers_from_settings(s: Settings) -> list[Provider]:
    out = []
    if s.groq_api_key and s.groq_api_key.get_secret_value():
        extra = {"reasoning_effort": "low"} if "gpt-oss" in s.groq_model else {}
        out.append(
            Provider(
                "groq",
                "https://api.groq.com/openai/v1",
                s.groq_api_key.get_secret_value(),
                s.groq_model,
                "gpt-oss" in s.groq_model or "qwen" in s.groq_model,
                extra,
            )
        )
    if s.openrouter_api_key and s.openrouter_api_key.get_secret_value():
        out.append(
            Provider(
                "openrouter",
                "https://openrouter.ai/api/v1",
                s.openrouter_api_key.get_secret_value(),
                s.openrouter_model,
                False,
            )
        )
    return out


@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    from_cache: bool
    latency_ms: float


class LLMClient:
    def __init__(
        self,
        providers: list[Provider],
        store: KVStore,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 6.0,
    ) -> None:
        self.providers = providers
        self.store = store
        self.http = http or httpx.AsyncClient()
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return bool(self.providers)

    @staticmethod
    def _checa_pii(messages: list[dict[str, str]]) -> None:
        for m in messages:
            ents = scan(m["content"])
            if ents:
                raise PiiBloqueada(f"PII {sorted({e.kind.value for e in ents})} no prompt ({m['role']})")

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 400,
        temperature: float = 0.0,
        cache_ns: str = "llm",
    ) -> LLMResult:
        if not self.providers:
            raise LLMIndisponivel("nenhum provedor configurado")
        self._checa_pii(messages)
        errors: list[str] = []
        for p in self.providers:
            key = (
                f"{cache_ns}:"
                + hashlib.sha256(
                    json.dumps(
                        [p.name, p.model, messages, schema, max_tokens, temperature], sort_keys=True
                    ).encode()
                ).hexdigest()[:32]
            )
            if (hit := await self.store.get_json(key)) is not None:
                return LLMResult(hit, p.name, p.model, True, 0.0)
            body: dict[str, Any] = {
                "model": p.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **p.extra,
            }
            if schema is not None:
                body["response_format"] = (
                    {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.get("title", "saida"),
                            "strict": True,
                            "schema": schema,
                        },
                    }
                    if p.json_schema
                    else {"type": "json_object"}
                )
            t0 = time.perf_counter()
            try:
                async with asyncio.timeout(self.timeout_s):
                    r = await self.http.post(
                        f"{p.base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {p.api_key}"},
                        timeout=self.timeout_s,
                    )
                if r.status_code == 400 and schema is not None and p.json_schema:
                    # modelo sem suporte ao schema estrito: tenta o modo JSON simples
                    body["response_format"] = {"type": "json_object"}
                    async with asyncio.timeout(self.timeout_s):
                        r = await self.http.post(
                            f"{p.base_url}/chat/completions",
                            json=body,
                            headers={"Authorization": f"Bearer {p.api_key}"},
                            timeout=self.timeout_s,
                        )
                if r.status_code != 200:
                    errors.append(f"{p.name}:{r.status_code}")
                    continue
                content = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    errors.append(f"{p.name}:vazio")
                    continue
                if schema is not None:
                    json.loads(_strip_fence(content))  # valida antes de cachear
            except (TimeoutError, httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                errors.append(f"{p.name}:{type(e).__name__}")
                continue
            await self.store.set_json(key, content, ttl_s=CACHE_TTL_S)
            return LLMResult(content, p.name, p.model, False, round((time.perf_counter() - t0) * 1000, 1))
        raise LLMIndisponivel(";".join(errors))


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


def parse_json(content: str) -> dict[str, Any]:
    data = json.loads(_strip_fence(content))
    if not isinstance(data, dict):
        raise ValueError("JSON não é objeto")
    return data
