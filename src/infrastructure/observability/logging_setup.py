"""Process-wide logging configuration, with PII redaction installed first.

Where this gets called
----------------------
Once per process, from the composition root of each entry point:
`create_app()` for the API, a Celery `setup_logging` signal for the worker,
`main()` for the CLI, and `tests/conftest.py` so the suite runs under the
same rules the deployed processes do.

Why the record factory
----------------------
Redaction has to hold for `logging.getLogger(__name__)` calls in every
module — including `application/`, which cannot import this package without
breaking the dependency rule, and including uvicorn, SQLAlchemy and Celery,
which never heard of it. Filters and formatters attach to *handlers*, and a
logger with `propagate = False` and a handler of its own (uvicorn.access is
exactly that) never reaches the root handler a filter was attached to.

`logging.setLogRecordFactory` has no such gap: every `LogRecord` any logger
anywhere creates goes through it. So the factory is the mechanism that makes
"redacts across all modules" true, and the filter and formatter installed
below are redundancy for the two paths a factory misses — records
reconstructed by `makeLogRecord` (queue/socket handlers), and a formatter
that re-renders `exc_info` instead of reusing `exc_text`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

from src.infrastructure.observability.pii_redaction import (
    PiiRedactingFilter,
    PiiRedactingFormatter,
    redact_record,
    redacting_formatters,
)

_DEFAULT_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class _RedactingRecordFactory:
    """The installed record factory: builds a record, then scrubs it.

    A class rather than a closure so that "is redaction installed?" and "what
    was here before?" are typed attributes instead of a pair of attributes
    bolted onto a function object. `install_pii_redaction` needs both to stay
    idempotent, and `reset_pii_redaction` needs the second to undo itself.
    """

    def __init__(self, previous: Callable[..., logging.LogRecord]) -> None:
        self.previous = previous

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        return redact_record(self.previous(*args, **kwargs))


def pii_redaction_installed() -> bool:
    """Whether this process is scrubbing log records.

    Public because it is the honest way for a test to assert that the control
    is on, and for an entry point to check rather than reinstall.
    """
    return isinstance(logging.getLogRecordFactory(), _RedactingRecordFactory)


def install_pii_redaction() -> None:
    """Route every new `LogRecord` in this process through `redact_record`.

    Idempotent, and composes with a factory somebody else installed: the
    previous factory still builds the record, and this wraps the result.
    """
    if pii_redaction_installed():
        return
    logging.setLogRecordFactory(_RedactingRecordFactory(logging.getLogRecordFactory()))


def reset_pii_redaction() -> None:
    """Restore the record factory that was in place before installation.

    For tests that need to prove the redaction is what is doing the work —
    without it, a test asserting "the raw address is absent" cannot tell a
    working scrubber from a log line that never contained an address.
    """
    current = logging.getLogRecordFactory()
    if isinstance(current, _RedactingRecordFactory):
        logging.setLogRecordFactory(current.previous)


def harden_existing_handlers() -> None:
    """Attach redaction to every handler already configured in this process.

    Called after installation so handlers set up by uvicorn or Celery — which
    configure logging on their own schedule, sometimes after ours — are
    covered too. Cheap enough to call more than once.
    """
    handlers: list[logging.Handler] = list(logging.getLogger().handlers)
    # Snapshot the registry before walking it: `getLogger` inserts into this
    # dict, and any thread doing that mid-iteration would raise. A logger
    # created after the snapshot is still covered — its records go through the
    # record factory, which is the control that matters.
    for logger in list(logging.root.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            handlers.extend(logger.handlers)

    for handler in handlers:
        if not any(isinstance(f, PiiRedactingFilter) for f in handler.filters):
            handler.addFilter(PiiRedactingFilter())
    redacting_formatters(handlers)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    force_handler: bool = True,
) -> None:
    """Install PII redaction and give the root logger a redacting handler.

    `force_handler` adds a `StreamHandler` when the root logger has none,
    which is the normal case for the CLI and the API. Passing it as False
    installs redaction over whatever handlers are already there without
    adding another — for a host (a test runner, a container log collector)
    that owns stdout itself.
    """
    install_pii_redaction()

    root = logging.getLogger()
    if force_handler and not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(PiiRedactingFormatter(_DEFAULT_FORMAT))
        handler.addFilter(PiiRedactingFilter())
        root.addHandler(handler)

    root.setLevel(level)
    harden_existing_handlers()
