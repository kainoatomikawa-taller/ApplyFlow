"""Infrastructure configuration.

Environment variables live ONLY in the infrastructure layer, per the
architecture contract. Domain and application never read env vars.

All secret-bearing values are typed as `SecretStr` so they render as
`**********` in reprs, logs, and tracebacks instead of their raw value.
Callers must explicitly call `.get_secret_value()` to obtain the real
value, and should only ever do so right at the point where a third-party
client requires a plain string.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "ApplyFlow"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True

    # Database (point this at Supabase's connection string outside of
    # local development — see README "Provisioning the database & auth".)
    database_url: str = (
        "postgresql+asyncpg://applyflow:applyflow@localhost:5432/applyflow"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    # Supabase (database host + auth provider)
    supabase_url: str = ""
    supabase_jwt_secret: SecretStr = SecretStr("")

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # LLM / LangChain (OpenAI — used by LangChainResumeAnalyzer)
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2

    # Anthropic — the ONLY LLM credential path (see AnthropicLlmClient).
    # Must be a pay-as-you-go API key from console.anthropic.com; never a
    # claude.ai subscription/session credential.
    anthropic_api_key: SecretStr = SecretStr("")
    # Model routing: callers pick a LlmTaskType, never a model. These two
    # settings are the only override point for which concrete model backs
    # each cost tier — see AnthropicLlmClient and TASK_TYPE_TIERS.
    anthropic_model_cheap: str = "claude-haiku-4-5-20251001"
    anthropic_model_strong: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 1024
    # Retry/backoff for transient errors (rate limits, timeouts, 5xxs) — see
    # AnthropicLlmClient. `anthropic_max_retries` is retries AFTER the initial
    # attempt, so total attempts = anthropic_max_retries + 1. Delay doubles
    # each attempt starting at the base and is capped at the max.
    anthropic_max_retries: int = 3
    anthropic_retry_base_delay_seconds: float = 1.0
    anthropic_retry_max_delay_seconds: float = 20.0

    # Job aggregator integration (reserved for an upcoming adapter)
    job_aggregator_api_key: SecretStr = SecretStr("")
    job_aggregator_base_url: str = ""

    # Search API integration (reserved for an upcoming adapter)
    search_api_key: SecretStr = SecretStr("")
    search_api_base_url: str = ""

    @model_validator(mode="after")
    def _require_secrets_outside_development(self) -> Settings:
        if self.environment == "development":
            return self
        if not self.openai_api_key.get_secret_value():
            raise ValueError(
                f"OPENAI_API_KEY is required when ENVIRONMENT is '{self.environment}'."
            )
        if not self.supabase_jwt_secret.get_secret_value():
            raise ValueError(
                "SUPABASE_JWT_SECRET is required when ENVIRONMENT is "
                f"'{self.environment}'."
            )
        if not self.anthropic_api_key.get_secret_value():
            raise ValueError(
                "ANTHROPIC_API_KEY is required when ENVIRONMENT is "
                f"'{self.environment}'."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
