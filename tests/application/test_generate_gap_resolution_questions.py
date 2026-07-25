"""Tests for GenerateGapResolutionQuestions — turns a list of gaps into
one neutrally-phrased question per gap, in order, and suppresses any gap a
remembered answer already covers so it is never re-asked.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from src.application.dtos.gap_resolution_dtos import (
    GenerateGapResolutionQuestionsInput,
)
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.value_objects.provenance_source import ProvenanceSource

# Orthogonal unit vectors per topic: two texts about the same topic embed
# identically (cosine 1.0) however differently they're worded, and texts
# about different topics embed at cosine 0.0 — which is what lets these
# tests exercise semantic matching without a real embedding model.
_TOPIC_VECTORS = {
    "kubernetes": [1.0, 0.0, 0.0],
    "leadership": [0.0, 1.0, 0.0],
    "python": [0.0, 0.0, 1.0],
}
_UNKNOWN_TOPIC_VECTOR = [0.5, 0.5, 0.5]  # cosine 0.577 to every topic axis


class FakeGenerator(GapResolutionQuestionGeneratorPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_question(self, *, gap: str) -> str:
        self.calls.append(gap)
        return f"Question about: {gap}"


class TopicEmbeddingClient(EmbeddingClientPort):
    """Embeds text as the unit vector of whichever known topic it
    mentions, standing in for a real model's property that reworded but
    equivalent text lands close together in vector space."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        lowered = text.lower()
        for topic, vector in _TOPIC_VECTORS.items():
            if topic in lowered:
                return list(vector)
        return list(_UNKNOWN_TOPIC_VECTOR)


class InMemoryAnswerMemoryRepo(AnswerMemoryRepository):
    def __init__(self) -> None:
        self.store: dict[str, AnswerMemory] = {}
        self.list_calls: list[str] = []

    async def add(self, answer_memory: AnswerMemory) -> None:
        self.store[answer_memory.id] = answer_memory

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        return self.store.get(answer_memory_id)

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        self.list_calls.append(user_id)
        return [a for a in self.store.values() if a.user_id == user_id]

    async def delete(self, answer_memory_id: str) -> None:
        self.store.pop(answer_memory_id, None)


def _remembered(
    *,
    id: str = "mem-1",
    user_id: str = "user-1",
    question_text: str = "Question about: Kubernetes",
    answer_text: str = "Ran a 40-node cluster for two years.",
    embedding: list[float] | None = None,
) -> AnswerMemory:
    return AnswerMemory(
        id=id,
        user_id=user_id,
        question_text=question_text,
        answer_text=answer_text,
        embedding=embedding if embedding is not None else _TOPIC_VECTORS["kubernetes"],
        source=ProvenanceSource.ANSWER,
    )


def _use_case(
    generator: FakeGenerator,
    repo: InMemoryAnswerMemoryRepo,
    embedding_client: TopicEmbeddingClient,
) -> GenerateGapResolutionQuestions:
    return GenerateGapResolutionQuestions(
        generator=generator,
        answer_memory_repository=repo,
        embedding_client=embedding_client,
    )


@pytest.mark.asyncio
async def test_generates_one_question_per_gap_in_order():
    generator = FakeGenerator()
    use_case = _use_case(generator, InMemoryAnswerMemoryRepo(), TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1",
            gaps=["Kubernetes", "Leadership experience", "5+ years of Python"],
        )
    )

    assert [item.gap for item in result.questions] == [
        "Kubernetes",
        "Leadership experience",
        "5+ years of Python",
    ]
    assert [item.question for item in result.questions] == [
        "Question about: Kubernetes",
        "Question about: Leadership experience",
        "Question about: 5+ years of Python",
    ]
    assert result.already_answered == []
    assert generator.calls == [
        "Kubernetes",
        "Leadership experience",
        "5+ years of Python",
    ]


@pytest.mark.asyncio
async def test_empty_gap_list_yields_no_questions_and_no_calls():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = TopicEmbeddingClient()
    use_case = _use_case(generator, repo, embedding_client)

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=[])
    )

    assert result.questions == []
    assert result.already_answered == []
    assert generator.calls == []
    assert repo.list_calls == []
    assert embedding_client.calls == []


@pytest.mark.asyncio
async def test_gap_covered_by_a_remembered_answer_is_not_asked_again():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered())
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1", gaps=["Kubernetes", "Leadership experience"]
        )
    )

    assert [item.gap for item in result.questions] == ["Leadership experience"]
    assert [item.gap for item in result.already_answered] == ["Kubernetes"]
    assert result.already_answered[0].answer_memory_id == "mem-1"
    assert result.already_answered[0].similarity_score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_reworded_gap_still_matches_the_remembered_answer():
    """The whole point of embedding-based matching: the earlier answer was
    stored against a differently-worded question about the same topic."""
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(
        _remembered(
            question_text="Tell me about your hands-on Kubernetes work.",
        )
    )
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1",
            gaps=["Production Kubernetes operations at scale"],
        )
    )

    assert result.questions == []
    assert [item.gap for item in result.already_answered] == [
        "Production Kubernetes operations at scale"
    ]


@pytest.mark.asyncio
async def test_unrelated_remembered_answers_do_not_suppress_a_gap():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(
        _remembered(
            question_text="Question about: Python",
            embedding=_TOPIC_VECTORS["python"],
        )
    )
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    assert [item.gap for item in result.questions] == ["Kubernetes"]
    assert result.already_answered == []


@pytest.mark.asyncio
async def test_another_users_remembered_answer_never_suppresses_a_gap():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered(id="mem-other", user_id="user-2"))
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    assert [item.gap for item in result.questions] == ["Kubernetes"]
    assert result.already_answered == []


@pytest.mark.asyncio
async def test_best_matching_remembered_answer_is_the_one_reported():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered(id="mem-partial", embedding=[1.0, 0.3, 0.0]))
    await repo.add(_remembered(id="mem-exact"))
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    assert [item.answer_memory_id for item in result.already_answered] == ["mem-exact"]


@pytest.mark.asyncio
async def test_a_weak_match_is_still_asked_under_the_default_threshold():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    # cosine 0.707 against the Kubernetes axis — below the 0.85 default.
    await repo.add(_remembered(embedding=[1.0, 1.0, 0.0]))
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    assert [item.gap for item in result.questions] == ["Kubernetes"]
    assert result.already_answered == []


@pytest.mark.asyncio
async def test_a_looser_threshold_suppresses_the_same_weak_match():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered(embedding=[1.0, 1.0, 0.0]))
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1", gaps=["Kubernetes"], similarity_threshold=0.7
        )
    )

    assert result.questions == []
    assert [item.gap for item in result.already_answered] == ["Kubernetes"]


@pytest.mark.asyncio
async def test_remembered_answers_are_fetched_once_for_the_whole_run():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered())
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1", gaps=["Kubernetes", "Leadership experience", "Python"]
        )
    )

    assert repo.list_calls == ["user-1"]


@pytest.mark.asyncio
async def test_no_embedding_call_when_the_candidate_has_nothing_remembered():
    """A first-time candidate has nothing to match against, so the
    embedding provider is never called on their behalf."""
    generator = FakeGenerator()
    embedding_client = TopicEmbeddingClient()
    use_case = _use_case(generator, InMemoryAnswerMemoryRepo(), embedding_client)

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            user_id="user-1", gaps=["Kubernetes", "Leadership experience"]
        )
    )

    assert len(result.questions) == 2
    assert embedding_client.calls == []


@pytest.mark.asyncio
async def test_embeds_the_generated_question_not_the_raw_gap():
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered(embedding=_TOPIC_VECTORS["python"]))
    embedding_client = TopicEmbeddingClient()
    use_case = _use_case(generator, repo, embedding_client)

    await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    assert embedding_client.calls == ["Question about: Kubernetes"]


@pytest.mark.asyncio
async def test_already_answered_report_discloses_no_stored_answer_text():
    """`AnswerMemory` is sensitive in full, so the "we already know this"
    signal points at the record without echoing its contents."""
    generator = FakeGenerator()
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_remembered(answer_text="I earn $250,000 and need a visa."))
    use_case = _use_case(generator, repo, TopicEmbeddingClient())

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-1", gaps=["Kubernetes"])
    )

    reported = asdict(result.already_answered[0])
    assert set(reported) == {"gap", "answer_memory_id", "similarity_score"}
    assert "visa" not in str(reported)
    assert "250,000" not in str(reported)
