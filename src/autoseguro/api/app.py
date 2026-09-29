"""API assíncrona do agente.

Canal: POST /v1/messages (resposta síncrona) e GET .../outbox (mensagens ativas).
Operador: fila de handoff, responder, devolver ao bot, encerrar. Rastreio: trace e histórico.
Rodar: uv run uvicorn autoseguro.api.app:app --port 8080
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AutoSeguroAgent(get_settings()) as agent:
        app.state.agent = agent
        yield


app = FastAPI(title="AutoSeguro Agent", version="0.5.0", lifespan=lifespan)


class MensagemIn(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1, max_length=4000)
    message_type: Literal["text", "image", "audio", "document"] = "text"
    message_id: str | None = Field(default=None, max_length=100)


def agent() -> AutoSeguroAgent:
    return app.state.agent


def _confere(chave, recebida: str | None) -> bool:
    return bool(chave) and recebida is not None and hmac.compare_digest(recebida, chave.get_secret_value())


def exige_chave(x_api_key: str | None = Header(default=None)) -> None:
    """Trace: sempre exige TRACE_API_KEY."""
    if not _confere(get_settings().trace_api_key, x_api_key):
        raise HTTPException(401, "chave inválida")


def exige_chave_canal(x_channel_key: str | None = Header(default=None)) -> None:
    """Entrada de mensagens: exige CHANNEL_API_KEY quando configurada (o Omni envia no header)."""
    chave = get_settings().channel_api_key
    if chave and not _confere(chave, x_channel_key):
        raise HTTPException(401, "chave do canal inválida")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/messages", dependencies=[Depends(exige_chave_canal)])
async def receber(m: MensagemIn, ag: AutoSeguroAgent = Depends(agent)):
    return await ag.handle(m.conversation_id, m.text, m.message_type, m.message_id)


@app.get("/v1/conversations/{conversation_id}/outbox", dependencies=[Depends(exige_chave_canal)])
async def outbox(conversation_id: str, depois_de: int = 0, ag: AutoSeguroAgent = Depends(agent)):
    """Mensagens ativas (cotação em segundo plano, humano, devolução) para o canal entregar."""
    return await ag.mensagens_ativas(conversation_id, depois_de)


class AcaoOperador(BaseModel):
    acao: Literal["responder", "devolver", "encerrar"]
    texto: str | None = Field(default=None, max_length=4000)


@app.post("/v1/conversations/{conversation_id}/operador", dependencies=[Depends(exige_chave)])
async def operador(conversation_id: str, a: AcaoOperador, ag: AutoSeguroAgent = Depends(agent)):
    """Painel do vendedor: responder o lead, devolver a conversa ao bot ou encerrar."""
    try:
        return await ag.operador(conversation_id, a.acao, a.texto)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/v1/handoffs", dependencies=[Depends(exige_chave)])
async def handoffs(ag: AutoSeguroAgent = Depends(agent)):
    """Fila do vendedor (dados mascarados)."""
    return await ag.handoffs.listar()


@app.get("/v1/conversations/{conversation_id}/historico", dependencies=[Depends(exige_chave)])
async def historico(conversation_id: str, ag: AutoSeguroAgent = Depends(agent)):
    """Cada checkpoint do LangGraph da conversa (viagem no tempo)."""
    return await ag.historico(conversation_id)


@app.get("/v1/conversations/{conversation_id}/trace", dependencies=[Depends(exige_chave)])
async def trace(conversation_id: str, ag: AutoSeguroAgent = Depends(agent)):
    t = await ag.trace(conversation_id)
    if t is None:
        raise HTTPException(404, "conversa não encontrada")
    return t
