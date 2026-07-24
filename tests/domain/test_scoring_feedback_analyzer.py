"""Tests for ScoringFeedbackAnalyzer — buckets thumbs-up/down feedback by
score and computes each bucket's agreement rate, the first step of the
documented path from raw feedback back into scoring.
"""

from __future__ import annotations

from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.services.scoring_feedback_analyzer import ScoringFeedbackAnalyzer
from src.domain.value_objects.feedback_rating import FeedbackRating


def _feedback(score: int, rating: FeedbackRating, suffix: str) -> JobMatchFeedback:
    return JobMatchFeedback(
        id=f"feedback-{suffix}",
        user_id="user-1",
        job_posting_id=f"job-{suffix}",
        rating=rating,
        score_at_feedback=score,
    )


def _analyze(feedback: list[JobMatchFeedback]):
    return ScoringFeedbackAnalyzer().analyze(feedback)


def test_no_feedback_yields_no_buckets():
    assert _analyze([]) == ()


def test_single_bucket_with_all_thumbs_up_has_full_agreement():
    feedback = [
        _feedback(90, FeedbackRating.THUMBS_UP, "a"),
        _feedback(85, FeedbackRating.THUMBS_UP, "b"),
    ]
    result = _analyze(feedback)
    assert len(result) == 1
    bucket = result[0]
    assert bucket.range_start == 80
    assert bucket.range_end == 100
    assert bucket.thumbs_up == 2
    assert bucket.thumbs_down == 0
    assert bucket.total == 2
    assert bucket.agreement_rate == 1.0


def test_mixed_feedback_in_one_bucket_computes_partial_agreement():
    feedback = [
        _feedback(65, FeedbackRating.THUMBS_UP, "a"),
        _feedback(70, FeedbackRating.THUMBS_DOWN, "b"),
        _feedback(60, FeedbackRating.THUMBS_DOWN, "c"),
    ]
    result = _analyze(feedback)
    assert len(result) == 1
    bucket = result[0]
    assert bucket.range_start == 60
    assert bucket.range_end == 80
    assert bucket.thumbs_up == 1
    assert bucket.thumbs_down == 2
    assert bucket.agreement_rate == 1 / 3


def test_score_of_exactly_100_lands_in_the_top_bucket():
    result = _analyze([_feedback(100, FeedbackRating.THUMBS_UP, "a")])
    assert len(result) == 1
    assert result[0].range_start == 80
    assert result[0].range_end == 100


def test_score_of_zero_lands_in_the_bottom_bucket():
    result = _analyze([_feedback(0, FeedbackRating.THUMBS_DOWN, "a")])
    assert len(result) == 1
    assert result[0].range_start == 0
    assert result[0].range_end == 20


def test_buckets_are_returned_sorted_ascending_and_only_for_data_present():
    feedback = [
        _feedback(95, FeedbackRating.THUMBS_UP, "a"),
        _feedback(5, FeedbackRating.THUMBS_DOWN, "b"),
    ]
    result = _analyze(feedback)
    assert [b.range_start for b in result] == [0, 80]
    # No feedback fell in 20-40/40-60/60-80 -> no fabricated empty buckets.
    assert len(result) == 2


def test_bucket_with_no_feedback_has_no_agreement_rate():
    # Constructed directly rather than via analyze(), since analyze()
    # never produces an empty bucket — this documents the "no data yet"
    # contract on ScoreBucketAgreement itself.
    from src.domain.services.scoring_feedback_analyzer import ScoreBucketAgreement

    bucket = ScoreBucketAgreement(range_start=40, range_end=60)
    assert bucket.total == 0
    assert bucket.agreement_rate is None
