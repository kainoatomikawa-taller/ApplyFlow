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
    # Embeddings (part of the Epic 00 LLM layer, see OpenAiEmbeddingClient).
    # Anthropic has no embeddings endpoint, so this reuses the OpenAI
    # credential above rather than the Anthropic one below.
    openai_embedding_model: str = "text-embedding-3-small"

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

    # Resume file storage (src/infrastructure/storage/local_file_storage.py).
    # Raw resume bytes are written here, addressed only by an opaque
    # server-generated key — never a candidate's filename or email — so
    # this directory's contents and any path logged from it carry no PII.
    resume_storage_dir: str = "./var/resumes"

    # Job aggregator integration — Adzuna (see
    # src/infrastructure/job_aggregators/adzuna_client.py). Adzuna
    # authenticates with a pair of credentials: `app_id` identifies the
    # calling application (not secret — Adzuna's own docs show it in
    # sample URLs) and `app_key` is the actual secret, reusing the generic
    # `job_aggregator_api_key` name so other aggregators can slot into the
    # same settings later.
    job_aggregator_app_id: str = ""
    job_aggregator_api_key: SecretStr = SecretStr("")
    job_aggregator_base_url: str = "https://api.adzuna.com/v1/api/jobs"
    job_aggregator_country: str = "us"
    job_aggregator_results_per_page: int = 50
    # Retry/backoff for transient errors (rate limits, timeouts, 5xxs) —
    # same shape as the Anthropic settings above. Total attempts =
    # job_aggregator_max_retries + 1.
    job_aggregator_max_retries: int = 3
    job_aggregator_retry_base_delay_seconds: float = 1.0
    job_aggregator_retry_max_delay_seconds: float = 20.0

    # Search API integration — Brave Search
    # (src/infrastructure/search/brave_search_client.py). Used only to
    # LOCATE which ATS board (Greenhouse/Lever/Ashby) a company posts
    # through (see AtsListingResolver) — never to answer a listing's
    # apply URL/description directly. The free tier is a tight daily quota
    # (`search_api_daily_quota`), so a discovered board is cached
    # permanently by company (ResolvedCompanyBoardRepository — the same
    # company's board is never searched for twice) and the quota is
    # tracked in Redis (DailySearchQuota) so exhausting it degrades
    # ingestion gracefully instead of failing it.
    search_api_key: SecretStr = SecretStr("")
    search_api_base_url: str = "https://api.search.brave.com/res/v1/web/search"
    search_api_daily_quota: int = 100
    search_api_max_retries: int = 3
    search_api_retry_base_delay_seconds: float = 1.0
    search_api_retry_max_delay_seconds: float = 20.0
    # How many ranked search results AtsListingResolver scans past a
    # company's marketing homepage looking for the first one that is
    # actually a recognized ATS board, before giving up on that company.
    search_api_board_locate_result_count: int = 5

    # ATS board integration — Greenhouse/Lever/Ashby public job-board APIs
    # (src/infrastructure/ats_boards/). These are unauthenticated public
    # feeds, so there are no credentials to configure here — only
    # retry/backoff, same shape as the other HTTP integrations above.
    ats_board_max_retries: int = 3
    ats_board_retry_base_delay_seconds: float = 1.0
    ats_board_retry_max_delay_seconds: float = 20.0

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
