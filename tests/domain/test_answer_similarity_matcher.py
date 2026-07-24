import pytest

from src.domain.entities.answer_memory import AnswerMemory
from src.domain.exceptions import InvalidValueError
from src.domain.services.answer_similarity_matcher import AnswerSimilarityMatcher
from src.domain.value_objects.provenance_source import ProvenanceSource


def _answer_memory(**overrides) -> AnswerMemory:
    defaults: dict = dict(
        id="am-1",
        user_id="user-1",
        question_text="Why do you want to work here?",
        answer_text="Because of the mission.",
        embedding=[1.0, 0.0],
        source=ProvenanceSource.ANSWER,
    )
    defaults.update(overrides)
    return AnswerMemory(**defaults)


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        score = AnswerSimilarityMatcher.cosine_similarity([1.0, 2.0], [1.0, 2.0])
        assert score == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        score = AnswerSimilarityMatcher.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert score == pytest.approx(0.0)

    def test_opposite_vectors_score_negative_one(self):
        score = AnswerSimilarityMatcher.cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert score == pytest.approx(-1.0)

    def test_scale_invariant(self):
        assert AnswerSimilarityMatcher.cosine_similarity(
            [1.0, 1.0], [50.0, 50.0]
        ) == pytest.approx(1.0)

    def test_zero_vector_scores_zero_rather_than_dividing_by_zero(self):
        assert AnswerSimilarityMatcher.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_empty_vector_rejected(self):
        with pytest.raises(InvalidValueError):
            AnswerSimilarityMatcher.cosine_similarity([], [1.0])

    def test_mismatched_length_rejected(self):
        with pytest.raises(InvalidValueError):
            AnswerSimilarityMatcher.cosine_similarity([1.0, 2.0], [1.0])


class TestFindBestMatch:
    def test_no_candidates_returns_none(self):
        matcher = AnswerSimilarityMatcher()
        assert matcher.find_best_match([1.0, 0.0], []) is None

    def test_returns_match_at_or_above_default_threshold(self):
        matcher = AnswerSimilarityMatcher()
        candidate = _answer_memory(embedding=[1.0, 0.01])

        match = matcher.find_best_match([1.0, 0.0], [candidate])

        assert match is not None
        assert match.answer_memory is candidate
        assert match.similarity_score >= AnswerSimilarityMatcher.DEFAULT_THRESHOLD

    def test_below_default_threshold_returns_none(self):
        matcher = AnswerSimilarityMatcher()
        dissimilar = _answer_memory(embedding=[0.0, 1.0])

        assert matcher.find_best_match([1.0, 0.0], [dissimilar]) is None

    def test_custom_threshold_admits_a_looser_match(self):
        matcher = AnswerSimilarityMatcher()
        loosely_related = _answer_memory(embedding=[1.0, 1.0])

        assert matcher.find_best_match([1.0, 0.0], [loosely_related]) is None
        match = matcher.find_best_match([1.0, 0.0], [loosely_related], threshold=0.5)
        assert match is not None
        assert match.answer_memory is loosely_related

    def test_returns_highest_scoring_candidate_among_several(self):
        matcher = AnswerSimilarityMatcher()
        closest = _answer_memory(id="am-closest", embedding=[1.0, 0.0])
        further = _answer_memory(id="am-further", embedding=[1.0, 0.3])

        match = matcher.find_best_match([1.0, 0.0], [further, closest], threshold=0.5)

        assert match is not None
        assert match.answer_memory.id == "am-closest"

    def test_candidates_below_threshold_are_excluded_even_if_relatively_best(self):
        matcher = AnswerSimilarityMatcher()
        still_far = _answer_memory(embedding=[0.1, 0.9])

        assert matcher.find_best_match([1.0, 0.0], [still_far], threshold=0.5) is None
