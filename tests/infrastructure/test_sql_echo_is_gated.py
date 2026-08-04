"""SQL echo must not be reachable outside development.

Found by the Epic 07 hardening pass. `DEBUG` defaults to `True`, and it was
wired straight into SQLAlchemy's `echo`, which logs every statement together
with its bound parameters. Those parameters arrive as a positional tuple, so the
PII scrubber has nothing to recognize them by — no value shape, no adjacent key
name — and ADR 0003 is explicit that shapeless values (a name, a street, the
prose of an answer) are exactly what it cannot see.

That made one forgotten `DEBUG=false` sufficient to write whole candidate
records, in the clear, into a log sink that sits outside the encryption boundary
and has no key rotation. Every other control in Epic 07 — the cipher, the access
gate, the call-site guard — would have held while this bypassed all of them.

Two tests here, and the second is the one that makes the first mean something:
the gate, and a demonstration that the scrubber genuinely cannot clean up after
echo. Without the second, someone could reasonably conclude the redaction layer
already covered this and remove the gate.
"""

from __future__ import annotations

import pytest

from src.infrastructure.config import Settings
from src.infrastructure.observability import redact
from src.infrastructure.persistence.database import sql_echo_enabled


def _settings(*, environment: str, debug: bool) -> Settings:
    return Settings(
        environment=environment,
        debug=debug,
        openai_api_key="x",
        anthropic_api_key="x",
        supabase_jwt_secret="x",
        field_encryption_keys="k1:" + "A" * 42 + "=",
        field_blind_index_key="k:" + "A" * 42 + "=",
    )


#: Every non-development value `Settings.environment` accepts. Written out rather
#: than derived, so adding a fourth environment fails here and forces someone to
#: decide whether echo is acceptable in it.
@pytest.mark.parametrize("environment", ["production", "staging"])
def test_sql_echo_is_off_outside_development_even_with_debug_on(
    environment: str,
) -> None:
    assert not sql_echo_enabled(_settings(environment=environment, debug=True))


def test_sql_echo_is_on_in_development_with_debug_on() -> None:
    """The gate is not a ban. Echo is genuinely useful, and in development the
    rows it prints are the developer's own fixtures."""
    assert sql_echo_enabled(_settings(environment="development", debug=True))


def test_sql_echo_is_off_when_debug_is_off() -> None:
    assert not sql_echo_enabled(_settings(environment="development", debug=False))


def test_the_scrubber_cannot_clean_up_after_sql_echo() -> None:
    """Why the gate has to exist rather than trusting redaction.

    This is what an echoed statement's parameters actually look like: a
    positional tuple with no key names. The scrubber's `key=value` rule has
    nothing to attach to, and none of these values has a recognizable shape, so
    they pass through untouched.

    If this test ever fails because the values *are* redacted, the scrubber has
    grown a rule that reads bare tuples — and the gate could then be
    reconsidered. Until then, this is the evidence for it.
    """
    echoed = (
        "[generated in 0.00021s] ('Jane Okonkwo', '17 Bellwether Lane', "
        "'Acme Robotics', 'Dear hiring manager, I am currently on an H-1B')"
    )
    assert redact(echoed) == echoed, (
        "If the scrubber now handles bare parameter tuples, revisit the SQL "
        "echo gate in src/infrastructure/persistence/database.py."
    )
