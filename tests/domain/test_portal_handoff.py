"""Tests for the PortalHandoff entity and its lifecycle.

What is under test is the property the acceptance criteria turn on: the state
is unambiguous while ApplyFlow is waiting, it can be resolved exactly once, and
resolving it says honestly *how* it was resolved. Also that a hand-off with
nothing to explain cannot be constructed — an unexplained halt is not something
a candidate can act on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind

_DETECTED_AT = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
_CAPTCHA = HardStop(
    kind=HardStopKind.CAPTCHA,
    evidence=("the page loads a known CAPTCHA component ('recaptcha')",),
)
_WALL = HardStop(
    kind=HardStopKind.ACCOUNT_WALL,
    evidence=("the form presents 1 password field",),
)


def _handoff(**overrides: object) -> PortalHandoff:
    defaults: dict[str, object] = {
        "handoff_id": "handoff-1",
        "user_id": "user-1",
        "job_posting_id": "job-1",
        "apply_url": "https://globex.example.com/apply/4242",
        "paused_url": "https://globex.example.com/login?next=/apply/4242",
        "hard_stops": (_CAPTCHA,),
        "detected_at": _DETECTED_AT,
    }
    defaults.update(overrides)
    return PortalHandoff.raise_for(**defaults)  # type: ignore[arg-type]


# ---- opening ----------------------------------------------------------------


def test_a_new_handoff_is_open_and_waiting_on_the_candidate():
    handoff = _handoff()

    assert handoff.status is HandoffStatus.AWAITING_USER
    assert handoff.is_open is True
    assert handoff.resolved_at is None
    assert handoff.resolution_note == ""


def test_last_detected_at_starts_equal_to_created_at():
    """Same instant, not "a few microseconds later" — a reader comparing the
    two should see "never re-detected", not a difference with no meaning."""
    handoff = _handoff()

    assert handoff.created_at == _DETECTED_AT
    assert handoff.last_detected_at == _DETECTED_AT


def test_a_handoff_reports_what_the_candidate_has_to_do():
    handoff = _handoff(hard_stops=(_CAPTCHA, _WALL))

    assert handoff.kinds == (HardStopKind.CAPTCHA, HardStopKind.ACCOUNT_WALL)
    assert len(handoff.required_human_actions) == 2
    assert handoff.evidence == (
        "the page loads a known CAPTCHA component ('recaptcha')",
        "the form presents 1 password field",
    )


def test_duplicate_kinds_are_reported_once_each():
    extra = HardStop(kind=HardStopKind.CAPTCHA, evidence=("the page reads 'captcha'",))
    handoff = _handoff(hard_stops=(_CAPTCHA, extra))

    assert handoff.kinds == (HardStopKind.CAPTCHA,)
    assert len(handoff.required_human_actions) == 1


# ---- invariants -------------------------------------------------------------


def test_a_handoff_with_no_boundary_is_refused():
    """A pause with no reason is not a hand-off."""
    with pytest.raises(InvalidValueError, match="at least one hard stop"):
        _handoff(hard_stops=())


def test_a_hard_stop_with_no_evidence_is_refused():
    with pytest.raises(InvalidValueError, match="at least one piece of evidence"):
        HardStop(kind=HardStopKind.CAPTCHA, evidence=())


def test_a_handoff_requires_the_urls_it_is_about():
    with pytest.raises(InvalidValueError, match="paused_url"):
        _handoff(paused_url="")


def test_an_open_handoff_cannot_carry_a_resolution():
    """The status and the resolution have to agree — a row saying both
    "waiting on you" and "resolved at 09:05" is uninterpretable."""
    with pytest.raises(InvalidValueError, match="cannot have a resolved_at"):
        PortalHandoff(
            id="handoff-1",
            user_id="user-1",
            job_posting_id="job-1",
            apply_url="https://x.example.com/apply",
            paused_url="https://x.example.com/login",
            hard_stops=(_CAPTCHA,),
            status=HandoffStatus.AWAITING_USER,
            resolved_at=_DETECTED_AT,
        )


def test_a_resolved_handoff_requires_a_resolution_time():
    with pytest.raises(InvalidValueError, match="requires a resolved_at"):
        PortalHandoff(
            id="handoff-1",
            user_id="user-1",
            job_posting_id="job-1",
            apply_url="https://x.example.com/apply",
            paused_url="https://x.example.com/login",
            hard_stops=(_CAPTCHA,),
            status=HandoffStatus.RESUMED,
        )


def test_an_over_long_note_is_refused():
    with pytest.raises(InvalidValueError, match="cannot exceed"):
        _handoff().resume(note="x" * (PortalHandoff.MAX_NOTE_LENGTH + 1))


# ---- resuming and abandoning ------------------------------------------------


def test_resuming_records_the_candidates_assertion_and_closes_the_handoff():
    resolved_at = _DETECTED_AT + timedelta(minutes=6)

    resumed = _handoff().resume(
        note="  Solved the captcha in Chrome  ", resolved_at=resolved_at
    )

    assert resumed.status is HandoffStatus.RESUMED
    assert resumed.is_open is False
    assert resumed.resolved_at == resolved_at
    assert resumed.resolution_note == "Solved the captcha in Chrome"


def test_abandoning_is_a_legitimate_ending():
    """ "I will finish this one myself" is an answer, not a failure — and it is
    what stops a hand-off from being stuck open forever on a portal that will
    always require an account."""
    abandoned = _handoff(hard_stops=(_WALL,)).abandon(note="Applying by hand")

    assert abandoned.status is HandoffStatus.ABANDONED
    assert abandoned.is_open is False
    assert abandoned.resolved_at is not None


def test_resolving_twice_is_refused():
    """The honest answer to a double-clicked "continue" is "that already
    happened", not a rewritten resolution time."""
    resumed = _handoff().resume()

    with pytest.raises(BusinessRuleViolationError, match="already resolved"):
        resumed.resume()
    with pytest.raises(BusinessRuleViolationError, match="already resolved"):
        resumed.abandon()


def test_resolving_leaves_the_original_untouched():
    """Frozen: a transition returns a new value, so a caller holding the
    hand-off keeps the state it decided on."""
    handoff = _handoff()

    handoff.resume(note="done")

    assert handoff.is_open is True
    assert handoff.resolution_note == ""


# ---- re-detection -----------------------------------------------------------


def test_re_detecting_refreshes_the_evidence_without_a_second_handoff():
    """Inspecting the same portal twice while the candidate has not acted
    keeps one hand-off, updated — a portal can present a different boundary
    on the second visit."""
    handoff = _handoff()
    later = _DETECTED_AT + timedelta(hours=2)

    refreshed = handoff.redetected(
        hard_stops=(_WALL,),
        paused_url="https://globex.example.com/account/create",
        detected_at=later,
    )

    assert refreshed.id == handoff.id
    assert refreshed.created_at == _DETECTED_AT
    assert refreshed.last_detected_at == later
    assert refreshed.kinds == (HardStopKind.ACCOUNT_WALL,)
    assert refreshed.paused_url.endswith("/account/create")
    assert refreshed.is_open is True


def test_a_resolved_handoff_cannot_be_re_detected_into():
    """A later boundary on the same portal is a new hand-off with its own
    evidence, not a reopening of one the candidate already cleared."""
    resumed = _handoff().resume()

    with pytest.raises(InvalidValueError, match="already resolved"):
        resumed.redetected(hard_stops=(_WALL,), paused_url="https://x.example.com/l")


# ---- status transitions -----------------------------------------------------


def test_awaiting_user_is_the_only_open_state():
    assert HandoffStatus.AWAITING_USER.is_open is True
    assert HandoffStatus.RESUMED.is_open is False
    assert HandoffStatus.ABANDONED.is_open is False


def test_both_resolutions_are_terminal():
    assert HandoffStatus.RESUMED.is_terminal is True
    assert HandoffStatus.ABANDONED.is_terminal is True
    assert HandoffStatus.AWAITING_USER.is_terminal is False
