"""FastAPI application entry point (interfaces layer).

This is the composition/bootstrap of the web adapter. It registers
controllers and cross-cutting concerns (CORS, error handling).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.persistence.database import dispose_engine
from src.interfaces.http.controllers import (
    application_controller,
    health_controller,
    job_match_feedback_controller,
    job_posting_controller,
    resume_controller,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # Release every pooled DB connection on shutdown instead of leaking
    # them until the process exits.
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ApplyFlow API",
        description="AI-assisted job application tracking & tailoring.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_controller.router)
    app.include_router(application_controller.router)
    app.include_router(resume_controller.router)
    app.include_router(job_posting_controller.router)
    app.include_router(job_match_feedback_controller.router)
    return app


app = create_app()
