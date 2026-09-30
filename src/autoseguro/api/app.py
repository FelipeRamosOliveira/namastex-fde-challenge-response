"""API assíncrona do agente.

Canal: POST /v1/messages (resposta síncrona) e GET .../outbox (mensagens ativas).
Operador: fila de handoff, responder, devolver ao bot, encerrar. Rastreio: trace e histórico.
Rodar: uv run uvicorn autoseguro.api.app:app --port 8080
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from autoseguro.agent.service import AutoSeguroAgent
from autoseguro.channels.omni import OmniWebhookPayload
from autoseguro.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    faltando = [n for n, v in (("CHANNEL_API_KEY", s.channel_api_key), ("VAULT_KEY", s.vault_key)) if not v]
    if s.exigir_segredos and faltando:
        raise RuntimeError(f"EXIGIR_SEGREDOS=true e faltam no .env: {', '.join(faltando)}")
    if not s.channel_api_key:
        logging.getLogger("autoseguro").warning("CHANNEL_API_KEY vazia: canal aberto (só dev)")
    async with AutoSeguroAgent(s) as agent:
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
    # bytes: compare_digest com str não ASCII levanta TypeError (500 em vez de 401)
    return (
        bool(chave)
        and recebida is not None
        and hmac.compare_digest(recebida.encode(), chave.get_secret_value().encode())
    )


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
async def health(ag: AutoSeguroAgent = Depends(agent)):
    """Saúde da API e estado do LLM (sem chave, o agente responde só com regras e avisa aqui)."""
    return {"status": "ok", "llm": ag.llm_status}


def _nao_omni(conversation_id: str) -> None:
    """Conversas do Omni só entram pelo /omni/webhook (autenticado pelo provider). Sem isso, quem
    souber o telefone escreveria na conversa real e leria as mensagens ativas dela."""
    if conversation_id.startswith("omni:"):
        raise HTTPException(403, "conversas do Omni entram só por /omni/webhook")


@app.post("/v1/messages", dependencies=[Depends(exige_chave_canal)])
async def receber(m: MensagemIn, ag: AutoSeguroAgent = Depends(agent)):
    _nao_omni(m.conversation_id)
    return await ag.handle(m.conversation_id, m.text, m.message_type, m.message_id)


def exige_bearer_omni(authorization: str | None = Header(default=None)) -> None:
    """O Omni manda `Authorization: Bearer <apiKey do provider>`.
    Sem OMNI_PROVIDER_KEY definida, o webhook fica fechado."""
    chave = get_settings().omni_provider_key
    recebida = (authorization or "").removeprefix("Bearer ").strip() or None
    if not _confere(chave, recebida):
        raise HTTPException(401, "provider do Omni não autorizado")


@app.post("/omni/webhook", dependencies=[Depends(exige_bearer_omni)])
async def omni_webhook(p: OmniWebhookPayload, ag: AutoSeguroAgent = Depends(agent)):
    """Provider `webhook` do Omni, modo round-trip: responde {"reply": ...} na hora.
    Mensagens depois (cotação em segundo plano, vendedor) saem por POST /api/v2/messages/send do Omni."""
    if not p.e_mensagem():
        return {"parts": []}  # reação, recibo, status: não é mensagem do lead
    texto, tipo = p.texto_e_tipo()
    out = await ag.handle(p.conversation_id(), texto, tipo, message_id=f"omni_{p.event.id}")
    if ag.omni is not None:
        await ag.omni.lembrar_rota(out["conversation_ref"], p)
    return {"reply": out["reply"]} if out["reply"] else {"parts": []}


@app.get("/v1/conversations/{conversation_id}/outbox", dependencies=[Depends(exige_chave_canal)])
async def outbox(conversation_id: str, depois_de: int = 0, ag: AutoSeguroAgent = Depends(agent)):
    """Mensagens ativas (cotação em segundo plano, humano, devolução) para o canal entregar."""
    _nao_omni(conversation_id)
    return await ag.mensagens_ativas(conversation_id, depois_de)


class AcaoOperador(BaseModel):
    acao: Literal["responder", "devolver", "encerrar"]
    texto: str | None = Field(default=None, max_length=4000)


@app.post("/v1/conversations/{conversation_id}/operador", dependencies=[Depends(exige_chave)])
async def operador(conversation_id: str, a: AcaoOperador, ag: AutoSeguroAgent = Depends(agent)):
    """Painel do vendedor: responder o lead, devolver a conversa ao bot ou encerrar.
    Use o `conversation_ref` (conv_...) que aparece em /v1/handoffs: o telefone não vai na URL."""
    try:
        return await ag.operador(conversation_id, a.acao, a.texto)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/v1/handoffs", dependencies=[Depends(exige_chave)])
async def handoffs(
    status: Literal["pendente", "em_atendimento", "devolvido", "encerrado"] | None = None,
    ag: AutoSeguroAgent = Depends(agent),
):
    """Fila do vendedor (dados mascarados). `?status=pendente` mostra só o que falta atender."""
    return await ag.handoffs.listar(status)


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
