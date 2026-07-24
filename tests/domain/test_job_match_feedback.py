"""Tests for JobMatchFeedback — a candidate's thumbs-up/down reaction to
one ranked job match."""

from __future__ import annotations

import pytest

from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.feedback_rating import FeedbackRating


def _feedback(**overrides: object) -> JobMatchFeedback:
    defaults: dict[str, object] = {
        "id": "feedback-1",
        "user_id": "user-1",
        "job_posting_id": "job-1",
        "rating": FeedbackRating.THUMBS_UP,
        "score_at_feedback": 80,
    }
    defaults.update(overrides)
    return JobMatchFeedback(**defaults)


def test_valid_feedback_constructs():
    feedback = _feedback()
    assert feedback.rating == FeedbackRating.THUMBS_UP
    assert feedback.score_at_feedback == 80


def test_empty_id_rejected():
    with pytest.raises(InvalidValueError):
        _feedback(id="")


def test_empty_user_id_rejected():
    with pytest.raises(InvalidValueError):
        _feedback(user_id="")


def test_empty_job_posting_id_rejected():
    with pytest.raises(InvalidValueError):
        _feedback(job_posting_id="")


def test_invalid_rating_type_rejected():
    with pytest.raises(InvalidValueError):
        _feedback(rating="thumbs_up")


@pytest.mark.parametrize("score", [-1, 101, -100, 1000])
def test_score_out_of_bounds_rejected(score):
    with pytest.raises(InvalidValueError):
        _feedback(score_at_feedback=score)


@pytest.mark.parametrize("score", [0, 50, 100])
def test_score_at_bounds_accepted(score):
    feedback = _feedback(score_at_feedback=score)
    assert feedback.score_at_feedback == score
