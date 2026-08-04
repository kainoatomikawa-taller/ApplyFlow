"""Behavioural tests for the log scrubber.

Two halves, and both matter:

* it removes what it claims to (emails, phones, national IDs, cards,
  credentials, query strings) from every part of a record — the message, the
  interpolated arguments, the traceback, and `extra=` fields;
* it leaves alone the identifiers and counters this codebase logs on purpose.
  Over-redaction is a real failure mode, not a safe default: a scrubber that
  ate `cache_read_input_tokens=500` would silently destroy the LLM cost
  logging, and the pressure would then be to turn the whole thing off.

`reset_pii_redaction` appears in several tests because a test asserting "the
address is not in the output" proves nothing unless it can also show the
address *would* have been there without the scrubber.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from src.infrastructure.observability import (
    configure_logging,
    install_pii_redaction,
    pii_redaction_installed,
    redact,
    reset_pii_redaction,
)
from src.infrastructure.observability.pii_redaction import PiiRedactingFilter


@pytest.fixture
def captured() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """A logger writing to a string buffer through a redacting handler, torn
    down afterwards so nothing leaks into other tests' logging."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(PiiRedactingFilter())

    logger = logging.getLogger("applyflow.test.redaction")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield logger, stream
    finally:
        logger.handlers = []


# ---- What must be removed -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("candidate is jane.doe+tag@example.co.uk", "jane.doe+tag@example.co.uk"),
        ("reachable on +44 20 7946 0958", "7946"),
        ("reachable on (415) 555-2671", "555-2671"),
        ("national id 123-45-6789", "123-45-6789"),
        ("paid with 4111 1111 1111 1111", "4111 1111 1111 1111"),
        ("Authorization: Bearer abc123.def456.ghi", "abc123.def456.ghi"),
        (
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqYW5lIn0.sig",
            "eyJhbGciOiJIUzI1NiJ9",
        ),
        (
            "GET https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=x&app_key=s3cret",
            "s3cret",
        ),
        (
            "GET https://api.search.brave.com/res/v1/web/search?q=jane+doe+resume",
            "jane+doe+resume",
        ),
        ("street_address=17 Bellwether Lane", "Bellwether"),
        ("{'full_name': 'Jane Okonkwo', 'city': 'Lagos'}", "Jane Okonkwo"),
        ("visa_type=H-1B", "H-1B"),
    ],
)
def test_recognizable_personal_data_is_removed(text: str, leaked: str) -> None:
    # The fixture text really does contain what we claim, so a typo in the
    # parametrization cannot turn into a passing test.
    assert leaked in text
    assert leaked not in redact(text)
    assert "[redacted:" in redact(text)


def test_redaction_is_idempotent() -> None:
    """Both the record factory and the formatter call `redact`, and a record
    handled by two handlers passes through more than once."""
    once = redact("write to jane@example.com or +1 (555) 010-9999")
    assert redact(once) == once


# ---- What must survive ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # LLM cost telemetry — the reason credential words are suffix-matched
        # rather than wildcard-matched.
        "anthropic prompt cache hit: cache_read_input_tokens=500 input_tokens=12",
        # Internal identifiers: the whole point of logging.
        "application=8f14e45f-ceea-467a-9a1e-1b2c3d4e5f60 moved applied -> screening",
        "review_id=r-42 job_posting_id=j-7 answers=3",
        # A sensitive *slot name* is a label, not a value.
        "answered a field (slot=phone, sensitivity=legal_attestation)",
        # Timestamps, versions, digests, counters.
        "at 2026-08-03T12:44:01Z version 1.2.3.4 sha256=deadbeefcafe1234567890abcdef",
        "epoch 1735689600000 limit=100 open_only=False",
        # A URL with no query string keeps its path.
        "board request to https://boards.greenhouse.io/embed/job_board failed",
    ],
)
def test_operational_detail_is_not_redacted(text: str) -> None:
    assert redact(text) == text


def test_a_bare_request_path_has_its_sensitive_query_values_redacted() -> None:
    """An access-log line carries a path, not an absolute URL, so the
    whole-query-string rule (which needs a scheme) does not fire on it. The
    key/value and value-shape rules do, which is what keeps an access log safe
    if one is ever enabled — the query string's *structure* survives, and only
    sensitive values go.
    """
    scrubbed = redact("GET /api/applications?candidate_email=jane@x.com HTTP/1.1 200")
    assert "jane@x.com" not in scrubbed
    assert "/api/applications" in scrubbed
    assert "200" in scrubbed

    # A non-shaped value is caught by its key alone.
    assert "Jane Doe" not in redact("GET /x?full_name=Jane Doe HTTP/1.1")

    # And an ordinary paginated request is untouched.
    path = "GET /api/tracked-applications?open_only=true&limit=100 HTTP/1.1 200"
    assert redact(path) == path


def test_a_url_keeps_its_host_and_path_when_the_query_goes() -> None:
    """The retry/backoff logs exist to say *which service* failed. Dropping the
    whole URL would satisfy the privacy rule and destroy their only purpose."""
    scrubbed = redact(
        "adzuna failed: https://api.adzuna.com/v1/api/jobs/gb/search/1?app_key=s"
    )
    assert "https://api.adzuna.com/v1/api/jobs/gb/search/1" in scrubbed
    assert "app_key" not in scrubbed


# ---- Integration with the logging machinery -------------------------------


def test_an_email_passed_as_a_log_argument_is_redacted(captured) -> None:
    logger, stream = captured
    install_pii_redaction()
    logger.info("created application for %s", "jane@example.com")
    assert "jane@example.com" not in stream.getvalue()
    assert "[redacted:email]" in stream.getvalue()


def test_without_the_scrubber_the_same_call_leaks(captured) -> None:
    """The control for the test above: proves the redaction is what removed the
    address, not the fixture or the format string."""
    logger, stream = captured
    reset_pii_redaction()
    try:
        logger.handlers[0].filters = []
        logger.info("created application for %s", "jane@example.com")
        assert "jane@example.com" in stream.getvalue()
    finally:
        install_pii_redaction()


def test_a_traceback_is_redacted(captured) -> None:
    logger, stream = captured
    install_pii_redaction()
    try:
        raise ValueError("could not parse resume for jane@example.com")
    except ValueError:
        logger.exception("resume parsing failed")

    output = stream.getvalue()
    assert "jane@example.com" not in output
    assert "[redacted:email]" in output
    # The traceback itself is still there — redaction must not cost the frames.
    assert "ValueError" in output
    assert "Traceback" in output


def test_extra_fields_are_redacted(captured) -> None:
    logger, stream = captured
    install_pii_redaction()
    handler = logger.handlers[0]
    handler.setFormatter(logging.Formatter("%(message)s | %(candidate)s"))
    logger.info("submitted", extra={"candidate": "jane@example.com"})
    assert "jane@example.com" not in stream.getvalue()


def test_a_record_reconstructed_from_a_dict_is_redacted_by_the_filter() -> None:
    """`makeLogRecord` bypasses the record factory — this is how queue and
    socket handlers ship logs between processes, so the filter has to cover it
    independently."""
    reset_pii_redaction()
    try:
        record = logging.makeLogRecord(
            {"msg": "candidate %s applied", "args": ("jane@example.com",)}
        )
        assert PiiRedactingFilter().filter(record) is True
        assert "jane@example.com" not in record.getMessage()
    finally:
        install_pii_redaction()


def test_a_broken_format_string_still_logs_something(captured) -> None:
    """A logging call must never take down the code path it was observing, so a
    mismatched format string degrades to a repr rather than raising."""
    logger, stream = captured
    install_pii_redaction()
    logger.info("two placeholders %s %s", "only-one")
    assert stream.getvalue().strip()


def test_configure_logging_is_idempotent() -> None:
    """Called from `create_app`, the Celery signal, and the CLI — and more than
    once in a process that imports two of them."""
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging(force_handler=False)
        configure_logging(force_handler=False)
        assert pii_redaction_installed()
        # A second install must not stack a second wrapper around the first —
        # one `reset` has to be enough to get back to an unscrubbed factory.
        reset_pii_redaction()
        assert not pii_redaction_installed()
    finally:
        root.handlers = before
        install_pii_redaction()


def test_the_suite_runs_with_redaction_installed() -> None:
    """`tests/conftest.py` installs it, so log-assertion tests elsewhere are
    asserting against the same behaviour the deployed processes have."""
    assert (
        pii_redaction_installed()
    ), "expected tests/conftest.py to have installed PII redaction"
