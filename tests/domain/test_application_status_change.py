"""Unit tests for the ApplicationStatusChange value object.

What is worth testing here is the set of entries the type refuses to be. A
history is only useful as evidence if every entry in it is well-formed, and this
value object is the one place that can guarantee it — `TrackedApplication`
checks how entries relate to each other, but not what a single entry may say.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.application_status_change import ApplicationStatusChange

_WHEN = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def test_a_change_records_where_it_came_from_and_went_to() -> None:
    change = ApplicationStatusChange(
        status=ApplicationStatus.INTERVIEWING,
        changed_at=_WHEN,
        previous_status=ApplicationStatus.APPLIED,
        note="recruiter screen booked",
    )

    assert change.status is ApplicationStatus.INTERVIEWING
    assert change.previous_status is ApplicationStatus.APPLIED
    assert change.note == "recruiter screen booked"
    assert not change.is_initial


def test_the_first_entry_has_nothing_before_it() -> None:
    change = ApplicationStatusChange(status=ApplicationStatus.APPLIED, changed_at=_WHEN)

    assert change.previous_status is None
    assert change.is_initial


def test_a_change_is_immutable() -> None:
    """A status change is something that happened; editing one would be
    rewriting history rather than recording it."""
    change = ApplicationStatusChange(status=ApplicationStatus.APPLIED, changed_at=_WHEN)

    with pytest.raises(FrozenInstanceError):
        change.status = ApplicationStatus.OFFER  # type: ignore[misc]


def test_two_changes_with_the_same_values_are_equal() -> None:
    """Equality by value — an entry has no identity beyond what it says and its
    position in one application's history."""
    first = ApplicationStatusChange(status=ApplicationStatus.APPLIED, changed_at=_WHEN)
    second = ApplicationStatusChange(status=ApplicationStatus.APPLIED, changed_at=_WHEN)

    assert first == second


def test_a_move_to_draft_is_refused() -> None:
    """A tracked application exists because it was sent, so no entry in its
    history could legitimately name `draft`."""
    with pytest.raises(InvalidValueError, match="cannot record a move to"):
        ApplicationStatusChange(status=ApplicationStatus.DRAFT, changed_at=_WHEN)


def test_a_move_from_a_status_to_itself_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="to itself"):
        ApplicationStatusChange(
            status=ApplicationStatus.APPLIED,
            changed_at=_WHEN,
            previous_status=ApplicationStatus.APPLIED,
        )


def test_a_naive_timestamp_is_refused() -> None:
    """A history ordered across a DST change or a deploy in another region still
    has to order correctly."""
    with pytest.raises(InvalidValueError, match="timezone-aware"):
        ApplicationStatusChange(
            status=ApplicationStatus.APPLIED,
            changed_at=datetime(2026, 7, 25, 12, 0),
        )


def test_a_non_status_value_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="valid ApplicationStatus"):
        ApplicationStatusChange(status="interviewing", changed_at=_WHEN)  # type: ignore[arg-type]


def test_a_non_status_previous_value_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="previous_status"):
        ApplicationStatusChange(
            status=ApplicationStatus.INTERVIEWING,
            changed_at=_WHEN,
            previous_status="applied",  # type: ignore[arg-type]
        )


def test_an_over_long_note_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="cannot exceed"):
        ApplicationStatusChange(
            status=ApplicationStatus.APPLIED,
            changed_at=_WHEN,
            note="x" * (ApplicationStatusChange.MAX_NOTE_LENGTH + 1),
        )


def test_a_note_at_the_limit_is_accepted() -> None:
    change = ApplicationStatusChange(
        status=ApplicationStatus.APPLIED,
        changed_at=_WHEN,
        note="x" * ApplicationStatusChange.MAX_NOTE_LENGTH,
    )

    assert len(change.note) == ApplicationStatusChange.MAX_NOTE_LENGTH
