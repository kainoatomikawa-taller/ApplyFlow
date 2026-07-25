"""Cross-use-case check that answers gathered in the gap-resolution loop
are reused on the *next* application instead of being asked again.

Walks the real sequence over one shared answer-memory store:
`GenerateGapResolutionQuestions` asks about a gap on job A ->
`ResolveGapAnswer` persists the response (provenance `answer`, embedding
indexed) -> `GenerateGapResolutionQuestions` runs again for job B, whose
posting words the same requirement differently, and does not re-ask it.

The two use cases are wired independently here (they never call each
other) with fakes for the embedding provider and question writer, so the
reuse behavior is proven deterministically without an API key.
"""

from __future__ import annotations

import pytest

from src.application.dtos.gap_resolution_dtos import (
    GenerateGapResolutionQuestionsInput,
    ResolveGapAnswerInput,
)
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)
from src.application.use_cases.resolve_gap_answer import ResolveGapAnswer
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.value_objects.provenance_source import ProvenanceSource

_USER = "user-1"

# Job A and job B describe the same underlying requirement in different
# words, so they produce differently-worded questions about one topic.
_JOB_A_GAP = "Kubernetes experience"
_JOB_B_GAP = "Comfortable operating container orchestration in production"

_SALARY_GAP = "Compensation expectations"


class TopicQuestionGenerator(GapResolutionQuestionGeneratorPort):
    """Stands in for the LLM question writer: one distinctly-worded
    question per gap, so nothing here can pass by string equality."""

    _QUESTIONS = {
        _JOB_A_GAP: "Have you worked with Kubernetes before?",
        _JOB_B_GAP: "Tell me about any container-orchestration work you've done.",
        _SALARY_GAP: "What compensation range are you targeting?",
    }

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_question(self, *, gap: str) -> str:
        self.calls.append(gap)
        return self._QUESTIONS[gap]


class TopicEmbeddingClient(EmbeddingClientPort):
    """Embeds by topic, mimicking a real model's property that reworded
    but equivalent text lands close together in vector space."""

    _TOPICS = {
        "kubernetes": [1.0, 0.0, 0.0],
        "container-orchestration": [0.99, 0.1, 0.0],
        "compensation": [0.0, 0.0, 1.0],
    }

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        lowered = text.lower()
        for topic, vector in self._TOPICS.items():
            if topic in lowered:
                return list(vector)
        raise AssertionError(f"test embedding client saw unexpected text: {text!r}")


class InMemoryAnswerMemoryRepo(AnswerMemoryRepository):
    def __init__(self) -> None:
        self.store: dict[str, AnswerMemory] = {}

    async def add(self, answer_memory: AnswerMemory) -> None:
        self.store[answer_memory.id] = answer_memory

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        return self.store.get(answer_memory_id)

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        return [a for a in self.store.values() if a.user_id == user_id]

    async def delete(self, answer_memory_id: str) -> None:
        self.store.pop(answer_memory_id, None)


class SequentialIdGenerator(IdGeneratorPort):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"mem-{self._next}"


@pytest.fixture
def store() -> InMemoryAnswerMemoryRepo:
    return InMemoryAnswerMemoryRepo()


@pytest.fixture
def embedding_client() -> TopicEmbeddingClient:
    return TopicEmbeddingClient()


@pytest.fixture
def ask(
    store: InMemoryAnswerMemoryRepo, embedding_client: TopicEmbeddingClient
) -> GenerateGapResolutionQuestions:
    return GenerateGapResolutionQuestions(
        generator=TopicQuestionGenerator(),
        answer_memory_repository=store,
        embedding_client=embedding_client,
    )


@pytest.fixture
def capture(
    store: InMemoryAnswerMemoryRepo, embedding_client: TopicEmbeddingClient
) -> ResolveGapAnswer:
    return ResolveGapAnswer(
        repository=store,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    )


@pytest.mark.asyncio
async def test_an_answer_given_on_one_job_is_not_re_asked_on_the_next(
    ask: GenerateGapResolutionQuestions,
    capture: ResolveGapAnswer,
    store: InMemoryAnswerMemoryRepo,
) -> None:
    # Job A: the gap is open, so it gets asked.
    job_a = await ask.execute(
        GenerateGapResolutionQuestionsInput(user_id=_USER, gaps=[_JOB_A_GAP])
    )
    assert [item.gap for item in job_a.questions] == [_JOB_A_GAP]
    assert job_a.already_answered == []

    # The candidate answers it, and the answer is persisted with the only
    # provenance an AnswerMemory can carry, plus its question embedding.
    resolved = await capture.execute(
        ResolveGapAnswerInput(
            user_id=_USER,
            gap=_JOB_A_GAP,
            question_text=job_a.questions[0].question,
            answer_text="Yes — I ran a 40-node cluster for two years.",
        )
    )
    assert resolved.captured is True
    stored = store.store[resolved.answer_memory_id or ""]
    assert stored.source is ProvenanceSource.ANSWER
    assert stored.embedding == [1.0, 0.0, 0.0]

    # Job B words the same requirement differently — still not re-asked.
    job_b = await ask.execute(
        GenerateGapResolutionQuestionsInput(user_id=_USER, gaps=[_JOB_B_GAP])
    )
    assert job_b.questions == []
    assert [item.gap for item in job_b.already_answered] == [_JOB_B_GAP]
    assert job_b.already_answered[0].answer_memory_id == resolved.answer_memory_id


@pytest.mark.asyncio
async def test_an_unrelated_gap_on_the_next_job_is_still_asked(
    ask: GenerateGapResolutionQuestions,
    capture: ResolveGapAnswer,
) -> None:
    await capture.execute(
        ResolveGapAnswerInput(
            user_id=_USER,
            gap=_JOB_A_GAP,
            question_text="Have you worked with Kubernetes before?",
            answer_text="Yes — I ran a 40-node cluster for two years.",
        )
    )

    job_b = await ask.execute(
        GenerateGapResolutionQuestionsInput(
            user_id=_USER, gaps=[_JOB_B_GAP, _SALARY_GAP]
        )
    )

    assert [item.gap for item in job_b.questions] == [_SALARY_GAP]
    assert [item.gap for item in job_b.already_answered] == [_JOB_B_GAP]


@pytest.mark.asyncio
async def test_a_declined_gap_stays_open_and_is_asked_again(
    ask: GenerateGapResolutionQuestions,
    capture: ResolveGapAnswer,
    store: InMemoryAnswerMemoryRepo,
) -> None:
    """A decline persists nothing (see `GapAnswerPolicy`), so there is no
    remembered answer to suppress the gap next time — the candidate is
    never recorded as having experience they said they don't have."""
    resolved = await capture.execute(
        ResolveGapAnswerInput(
            user_id=_USER,
            gap=_JOB_A_GAP,
            question_text="Have you worked with Kubernetes before?",
            answer_text="nothing to add",
        )
    )
    assert resolved.captured is False
    assert store.store == {}

    job_b = await ask.execute(
        GenerateGapResolutionQuestionsInput(user_id=_USER, gaps=[_JOB_B_GAP])
    )

    assert [item.gap for item in job_b.questions] == [_JOB_B_GAP]
    assert job_b.already_answered == []


@pytest.mark.asyncio
async def test_one_users_answer_never_suppresses_another_users_gap(
    ask: GenerateGapResolutionQuestions,
    capture: ResolveGapAnswer,
) -> None:
    await capture.execute(
        ResolveGapAnswerInput(
            user_id=_USER,
            gap=_JOB_A_GAP,
            question_text="Have you worked with Kubernetes before?",
            answer_text="Yes — I ran a 40-node cluster for two years.",
        )
    )

    other = await ask.execute(
        GenerateGapResolutionQuestionsInput(user_id="user-2", gaps=[_JOB_B_GAP])
    )

    assert [item.gap for item in other.questions] == [_JOB_B_GAP]
    assert other.already_answered == []
