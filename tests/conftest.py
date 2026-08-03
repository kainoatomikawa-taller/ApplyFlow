"""Shared pytest configuration.

Ensures the project root is importable so `src.*` resolves during tests.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.security.sensitive_access import (  # noqa: E402
    SensitiveDataAccess,
    sensitive_data_access,
)


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
