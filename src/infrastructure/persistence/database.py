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

from src.infrastructure.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
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
