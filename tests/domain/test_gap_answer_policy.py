"""Tests for GapAnswerPolicy — recognizes a decline ("nothing to add")
response to a gap-resolution question without ever misreading a genuine
answer as one.
"""

from __future__ import annotations

import pytest

from src.domain.services.gap_answer_policy import GapAnswerPolicy


@pytest.mark.parametrize(
    "answer_text",
    [
        "",
        "   ",
        "no",
        "No",
        "NO.",
        "nope",
        "none",
        "n/a",
        "N/A",
        "na",
        "nothing",
        "nothing to add",
        "not applicable",
        "not really",
        "no experience",
        "skip",
        "  none  ",
    ],
)
def test_recognizes_decline_phrases(answer_text: str):
    assert GapAnswerPolicy.is_declined(answer_text) is True


@pytest.mark.parametrize(
    "answer_text",
    [
        "Yes, I led a team of 5 engineers for two years.",
        "No, but I did mentor two interns last summer.",
        "I ran a small project at my last job.",
        "Not a formal lead role, but I coordinated the migration effort.",
        "I have none of that, however I did organize our team's on-call rotation.",
    ],
)
def test_never_misreads_a_genuine_answer_as_a_decline(answer_text: str):
    assert GapAnswerPolicy.is_declined(answer_text) is False
