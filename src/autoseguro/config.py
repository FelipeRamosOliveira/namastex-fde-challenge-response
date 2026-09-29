"""Configuração central lida do ambiente (.env). Nenhum segredo tem valor padrão."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM (etapa 4) ---
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-20b"  # structured outputs estrito, ~1000 tokens/s
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openai/gpt-oss-20b:free"
    llm_timeout_s: float = 6.0
    usar_redator: bool = True  # frase natural antes da resposta, sem números

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
    vault_key: SecretStr | None = None  # chave Fernet: cifra o CEP guardado no checkpoint

    # --- Conversa ---
    max_turnos_sem_progresso: int = 6
    # Novas tentativas de cotação em segundo plano antes de ir para humano (segundos após cada falha)
    retry_fundo_delays_s: list[float] = [5.0, 20.0, 60.0]
    # Entrega ativa ao canal (Omni ou outro); sem URL, o canal busca em GET .../outbox
    outbound_webhook_url: str | None = None

    # --- Omni (canal) ---
    omni_url: str | None = None  # ex.: http://omni-api:8882 (para mensagens ativas)
    omni_api_key: SecretStr | None = None  # chave da API do Omni (x-api-key)
    omni_provider_key: SecretStr | None = None  # Bearer que o Omni manda no webhook do provider


@lru_cache
def get_settings() -> Settings:
    return Settings()
