"""SQLAlchemy async engine and session factory.

This module owns the connection pool's lifecycle: one process-wide engine
is created here, sized from config, and must be disposed of via
`dispose_engine()` on application shutdown (wired into the FastAPI
`lifespan` in `src/interfaces/http/app.py`).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.infrastructure.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_settings = get_settings()


def sql_echo_enabled(settings: Settings) -> bool:
    """Whether SQLAlchemy should log every statement and its parameters.

    Gated on the environment and not on `DEBUG` alone, and this is a privacy
    control rather than a noise preference.

    Echo logs each statement *with its bound parameters*, and those arrive as a
    positional tuple — `('Jane Okonkwo', '17 Bellwether Lane', ...)`. The PII
    scrubber (ADR 0003) recognizes a value either by its shape or by an adjacent
    key name, and a bare tuple offers neither, so exactly the categories that ADR
    documents the scrubber as unable to see — a person's name, a street, the
    prose of an answer — pass through echo untouched. One forgotten
    `DEBUG=false` would therefore write whole candidate records into a log sink
    that sits outside the encryption boundary and has no key rotation.

    So `DEBUG` keeps its meaning everywhere else and loses this one power outside
    development, where the rows are a developer's own fixtures. Deliberately not
    solved by refusing `DEBUG=true` in production: verbose logging is a
    legitimate thing to want during an incident, and a control that forces
    someone to choose between diagnosis and privacy is a control that gets
    switched off.

    A function rather than an inline expression so the rule is testable without
    re-importing this module under a different environment — see
    `tests/infrastructure/test_sql_echo_is_gated.py`.
    """
    return settings.debug and settings.environment == "development"


engine = create_async_engine(
    _settings.database_url.get_secret_value(),
    echo=sql_echo_enabled(_settings),
    future=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    # Recycles connections before a middlebox (e.g. Supabase's pooler) or
    # the server silently drops them, and verifies a connection is alive
    # before handing it out instead of surfacing a stale-connection error.
    pool_recycle=_settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    # Supabase's free-tier connection is PgBouncer in transaction-pooling
    # mode, which is incompatible with asyncpg's server-side prepared
    # statement cache. Disabling it is a no-op against a direct Postgres
    # connection (e.g. local dev), so this is safe for both.
    connect_args={"statement_cache_size": 0},
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session (FastAPI dependency)."""
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Close every pooled connection. Call once, on process shutdown."""
    await engine.dispose()
