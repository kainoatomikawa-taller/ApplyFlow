"""Shared pytest configuration.

Ensures the project root is importable so `src.*` resolves during tests, and
points the suite at its own database.

Why the database is redirected here, before any `src` import
-----------------------------------------------------------
The real-database smoke tests run against whatever `DATABASE_URL` names, and
they do not clean up after themselves — every `pytest` run left roughly 44 job
postings, plus profiles, documents and tracked applications, in the developer's
own database. Two things came of that: the dev database filled with thousands of
`Smoke Test Co` rows that pollute any real query, and
`test_job_posting_persistence_smoke.py` began failing permanently because its
`limit=1000` scan could no longer reach the row it had just written.

Redirecting to a separate database fixes the cause rather than the symptom, and
does it structurally: no individual test has to remember to tidy up, and a new
smoke test cannot reintroduce the problem by forgetting.

The assignment has to happen *before* `src.infrastructure.persistence.database`
is first imported, because that module builds its `engine` at import time from
`get_settings()`, which is `lru_cache`d. pytest imports this conftest before any
test module, so this is the earliest hook available — hence the deliberate
`os.environ` write above the `src` imports, and the `# noqa: E402` on them.

An environment variable rather than an edit to `.env.local`: pydantic-settings
ranks the process environment above dotenv files, so this wins even if a
`DATABASE_URL` is later set there, and it cannot be switched off by accident.
Override `APPLYFLOW_TEST_DATABASE_URL` to point the suite somewhere else.
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://applyflow:applyflow@localhost:5432/applyflow_test"
)
os.environ["DATABASE_URL"] = os.environ.get(
    "APPLYFLOW_TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL
)

from src.infrastructure.observability import install_pii_redaction  # noqa: E402
from src.infrastructure.security.sensitive_access import (  # noqa: E402
    SensitiveDataAccess,
    sensitive_data_access,
)

# The suite runs under the same redaction the deployed processes do (Epic 07).
# Without this, a test that asserts on a log line would be asserting against
# behaviour no real process has — and `caplog`-based tests are how the log
# sites in this codebase are covered. Only the record factory is installed,
# not a handler: pytest's own capture owns the root handler.
install_pii_redaction()


@pytest.fixture
def sensitive_access() -> Iterator[SensitiveDataAccess]:
    """Open a sensitive-data access scope for a test that reads encrypted
    columns (Epic 07 — see `src/infrastructure/security/sensitive_access.py`).

    A test that goes through a repository is standing in for an authorized entry
    point, so it has to declare access exactly as that entry point does. Any
    test touching a sensitive-flagged column needs this; without it the read
    raises `SensitiveAccessDeniedError`.

    Deliberately NOT autouse. An autouse scope would hold for the tests that
    exist to prove the gate refuses, quietly turning the whole control off
    across the suite — so the fixture has to be asked for by name, and its
    appearance in a signature says "this test reads sensitive data".
    """
    with sensitive_data_access(
        subject="test-suite", reason="automated test reading sensitive columns"
    ) as access:
        yield access
