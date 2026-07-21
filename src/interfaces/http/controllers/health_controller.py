"""Health check endpoint.

Also doubles as the shell's "hello world" — the frontend's status screen
hits this route to prove the web shell can reach the API and to display
which environment (from the config layer) it's talking to.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.infrastructure.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }
