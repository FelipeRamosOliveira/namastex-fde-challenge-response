"""Groq falso (API compatível com OpenAI) para testar a etapa 4 sem rede."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

VAZIO = {
    "idade": None,
    "veiculo_ano": None,
    "cep_token": None,
    "plano_id": None,
    "data_inicio": None,
    "intents": [],
}


class FakeLLM:
    """extrair(texto_do_lead) -> dict parcial; redigir(texto_do_lead) -> str."""

    def __init__(
        self,
        extrair: Callable[[str], dict] | None = None,
        redigir: Callable[[str], str] | None = None,
        status: dict[str, int] | None = None,
    ) -> None:
        self.extrair = extrair or (lambda t: {})
        self.redigir = redigir or (lambda t: "")
        self.status = status or {}
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), **body})
        host = request.url.host
        if host in self.status:
            return httpx.Response(self.status[host], json={"error": "x"})
        user = body["messages"][-1]["content"]
        lead = user.split("<mensagem_do_lead>\n", 1)[1].split("\n</mensagem_do_lead>", 1)[0]
        if "response_format" in body:
            content = json.dumps({**VAZIO, **self.extrair(lead)})
        else:
            content = self.redigir(lead)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def prompts(self) -> str:
        return "\n".join(m["content"] for r in self.requests for m in r["messages"])
