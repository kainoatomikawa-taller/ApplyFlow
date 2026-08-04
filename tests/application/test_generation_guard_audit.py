"""Tests for GenerationGuardAudit — the debugging record of what the
provenance guard removed.

A violation that isn't logged is a fabrication attempt nobody can
diagnose, so the content of these log lines is a real contract, not
incidental output.
"""

from __future__ import annotations

import logging

from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.domain.services.provenance_guard import (
    GuardedContent,
    ProvenanceViolation,
    SupportedLine,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource


def _record(guarded: GuardedContent, kind=GeneratedDocumentKind.TAILORED_RESUME):
    GenerationGuardAudit.record(
        document_kind=kind,
        user_id="user-1",
        job_posting_id="job-1",
        guarded=guarded,
    )


def test_a_violation_is_logged_at_warning_with_its_terms_and_identifiers(caplog):
    guarded = GuardedContent(
        violations=(
            ProvenanceViolation(
                line="Staff Engineer at Initech (2016-2019)",
                unsupported_terms=("staff", "initech"),
            ),
        )
    )

    with caplog.at_level(logging.DEBUG):
        _record(guarded)

    assert all(record.levelno == logging.WARNING for record in caplog.records)
    logged = caplog.text
    assert "tailored_resume" in logged
    assert "user-1" in logged
    assert "job-1" in logged
    assert "staff,initech" in logged


def test_the_stripped_line_itself_is_not_logged(caplog):
    """A line is stripped because its *claim* is unsupported, which says
    nothing about the other words in it — a real name in front of an invented
    achievement is still a real name (Epic 07 — no PII in logs). The
    actionable part, `unsupported_terms`, is logged in full instead."""
    guarded = GuardedContent(
        violations=(
            ProvenanceViolation(
                line="Sarah Okonkwo led a team of 40 at Initech",
                unsupported_terms=("led a team of 40",),
            ),
        )
    )

    with caplog.at_level(logging.DEBUG):
        _record(guarded)

    assert "Sarah Okonkwo" not in caplog.text
    assert "led a team of 40" in caplog.text


def test_every_violation_gets_its_own_line_plus_a_summary(caplog):
    guarded = GuardedContent(
        violations=(
            ProvenanceViolation(line="one", unsupported_terms=("a",)),
            ProvenanceViolation(line="two", unsupported_terms=("b",)),
        )
    )

    with caplog.at_level(logging.WARNING):
        _record(guarded)

    assert len(caplog.records) == 3
    assert "stripped 2 unsupported line(s)" in caplog.text


def test_the_document_kind_distinguishes_the_two_flows(caplog):
    guarded = GuardedContent(
        violations=(ProvenanceViolation(line="x", unsupported_terms=("x",)),)
    )

    with caplog.at_level(logging.WARNING):
        _record(guarded, kind=GeneratedDocumentKind.COVER_LETTER)

    assert "cover_letter" in caplog.text
    assert "tailored_resume" not in caplog.text


def test_a_clean_run_stays_quiet_above_debug(caplog):
    guarded = GuardedContent(
        lines=(
            SupportedLine(
                text="Skill: Python",
                backing_sources=(ProvenanceSource.PARSED_RESUME,),
            ),
        )
    )

    with caplog.at_level(logging.WARNING):
        _record(guarded)

    assert caplog.records == []


def test_a_clean_run_still_records_its_provenance_at_debug(caplog):
    guarded = GuardedContent(
        lines=(
            SupportedLine(
                text="Skill: Python",
                backing_sources=(ProvenanceSource.PARSED_RESUME,),
            ),
        )
    )

    with caplog.at_level(logging.DEBUG):
        _record(guarded)

    assert "provenance guard passed tailored_resume" in caplog.text
    assert "parsed_resume" in caplog.text


def test_content_that_passed_the_guard_is_never_logged(caplog):
    """Surviving text is the candidate's own data. Neither it nor the stripped
    line is written out — only the terms that failed."""
    guarded = GuardedContent(
        lines=(SupportedLine(text="Email: dana@example.com"),),
        violations=(
            ProvenanceViolation(
                line="Fabricated line", unsupported_terms=("fabricated",)
            ),
        ),
    )

    with caplog.at_level(logging.DEBUG):
        _record(guarded)

    assert "dana@example.com" not in caplog.text
    assert "Fabricated line" not in caplog.text
    assert "fabricated" in caplog.text
