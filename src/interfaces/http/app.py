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
    application_autofill_controller,
    application_controller,
    application_document_controller,
    application_review_controller,
    cover_letter_controller,
    document_revision_controller,
    gap_resolution_controller,
    health_controller,
    job_match_feedback_controller,
    job_posting_controller,
    portal_handoff_controller,
    resume_controller,
    tailored_resume_controller,
)
<<<<<<< HEAD
from src.interfaces.http.dependencies import shutdown_portal_automation
=======
from src.interfaces.http.dependencies import shutdown_browser_automation
>>>>>>> origin/main


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # Close the portal automation first: a parked review holds a browser
    # context, and a browser process outliving the API is what takes a host
    # down. It needs no database, so ordering it before the pool teardown
    # costs nothing.
    await shutdown_portal_automation()
    # Release every pooled DB connection on shutdown instead of leaking
    # them until the process exits.
    await dispose_engine()
    # And the shared Chromium, if any inspection ever launched one. A browser
    # process that outlives the API is what takes a host down over a restart
    # loop, so this is the backstop even though every session closes itself.
    await shutdown_browser_automation()


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
    app.include_router(gap_resolution_controller.router)
    app.include_router(tailored_resume_controller.router)
    app.include_router(cover_letter_controller.router)
    app.include_router(document_revision_controller.router)
    app.include_router(application_document_controller.router)
<<<<<<< HEAD
    # Two routers from one controller: the autofill lives under the posting it
    # is for, while a parked review is its own resource with its own lifetime.
    app.include_router(application_autofill_controller.autofill_router)
    app.include_router(application_autofill_controller.review_router)
=======
    app.include_router(portal_handoff_controller.router)
    app.include_router(application_review_controller.router)
>>>>>>> origin/main
    return app


app = create_app()
