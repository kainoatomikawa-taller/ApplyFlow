"""Infrastructure configuration.

Environment variables live ONLY in the infrastructure layer, per the
architecture contract. Domain and application never read env vars.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "ApplyFlow"
    environment: str = "development"
    debug: bool = True

    # Database
    database_url: str = (
        "postgresql+asyncpg://applyflow:applyflow@localhost:5432/applyflow"
    )

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # LLM / LangChain
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2


@lru_cache
def get_settings() -> Settings:
    return Settings()
