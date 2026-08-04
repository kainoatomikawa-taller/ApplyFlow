"""Observability infrastructure — logging configuration and PII scrubbing.

Nothing in `domain/` or `application/` imports from here. Application code
logs through the standard library exactly as it always did; this package is
installed once by each process entry point (HTTP app, Celery worker, CLI)
and takes effect globally from that moment on. See `logging_setup.py`.
"""

from __future__ import annotations

from src.infrastructure.observability.logging_setup import (
    configure_logging,
    harden_existing_handlers,
    install_pii_redaction,
    pii_redaction_installed,
    reset_pii_redaction,
)
from src.infrastructure.observability.pii_redaction import (
    PiiRedactingFilter,
    PiiRedactingFormatter,
    redact,
)

__all__ = [
    "PiiRedactingFilter",
    "PiiRedactingFormatter",
    "configure_logging",
    "harden_existing_handlers",
    "install_pii_redaction",
    "pii_redaction_installed",
    "redact",
    "reset_pii_redaction",
]
