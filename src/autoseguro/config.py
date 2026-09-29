"""Configuração central lida do ambiente (.env). Nenhum segredo tem valor padrão."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM (etapa 4) ---
    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # --- API de cotação do desafio ---
    quote_api_url: str = "http://localhost:8000"
    quote_timeout_s: float = 2.5  # corta a chamada lenta (8 s) cedo
    quote_hedge_after_s: float = 1.2  # dispara 2a chamada se a 1a demorar
    quote_max_attempts: int = 4  # total de chamadas por cotação
    quote_backoff_base_s: float = 0.2
    quote_backoff_max_s: float = 1.5
    breaker_failure_threshold: int = 3  # cotações falhas seguidas para abrir o circuito
    breaker_reset_s: float = 15.0  # tempo aberto antes de testar de novo
    planos_ttl_s: int = 3600

    # --- Infra ---
    redis_url: str | None = None  # sem Redis: cache e breaker em memória
    checkpoint_db: str = "data/runtime/checkpoints.sqlite"
    mcp_url: str | None = None  # sem URL: ferramentas MCP em processo
    trace_api_key: SecretStr | None = None  # protege GET /v1/conversations/{id}/trace
    channel_api_key: SecretStr | None = None  # se definida, exigida em POST /v1/messages

    # --- Conversa ---
    max_turnos_sem_progresso: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
