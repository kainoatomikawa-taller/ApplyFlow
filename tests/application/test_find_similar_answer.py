"""FindSimilarAnswer use case tests using in-memory fakes.

The embedding fake maps question text to hand-picked vectors so tests can
assert on semantic behavior (a reworded question landing near its
original) without depending on a real embedding model.
"""

import pytest

from src.application.dtos.answer_memory_dtos import FindSimilarAnswerInput
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.use_cases.find_similar_answer import FindSimilarAnswer
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.value_objects.provenance_source import ProvenanceSource


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


class TextKeyedEmbeddingClient(EmbeddingClientPort):
    """Returns a pre-registered vector for known text, or an explicit
    default for anything unregistered — lets tests simulate a real
    embedding model placing reworded-but-equivalent questions close
    together in vector space."""

    def __init__(self, vectors: dict[str, list[float]], default: list[float]) -> None:
        self._vectors = vectors
        self._default = default

    async def embed(self, text: str) -> list[float]:
        return self._vectors.get(text, self._default)


def _answer_memory(**overrides) -> AnswerMemory:
    defaults: dict = dict(
        id="am-1",
        user_id="user-1",
        question_text="Why do you want to work here?",
        answer_text="Because of the mission and the team.",
        embedding=[1.0, 0.0, 0.0],
        source=ProvenanceSource.ANSWER,
    )
    defaults.update(overrides)
    return AnswerMemory(**defaults)


@pytest.mark.asyncio
async def test_reworded_equivalent_question_resolves_to_same_saved_answer():
    repo = InMemoryAnswerMemoryRepo()
    stored = _answer_memory(
        question_text="Why do you want to work here?",
        embedding=[1.0, 0.0, 0.0],
    )
    await repo.add(stored)

    # "What interests you about this role?" is a rewording of the stored
    # question — its embedding lands very close to, but not exactly on,
    # the stored vector.
    embedding_client = TextKeyedEmbeddingClient(
        vectors={"What interests you about this role?": [0.99, 0.14, 0.0]},
        default=[0.0, 1.0, 0.0],
    )

    result = await FindSimilarAnswer(repo, embedding_client).execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="What interests you about this role?"
        )
    )

    assert result is not None
    assert result.answer.id == stored.id
    assert result.answer.answer_text == "Because of the mission and the team."
    assert result.similarity_score >= 0.85


@pytest.mark.asyncio
async def test_returns_provenance_alongside_the_matched_answer():
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_answer_memory())
    embedding_client = TextKeyedEmbeddingClient(vectors={}, default=[1.0, 0.0, 0.0])

    result = await FindSimilarAnswer(repo, embedding_client).execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="Why do you want to work here?"
        )
    )

    assert result is not None
    assert result.answer.source == ProvenanceSource.ANSWER.value


@pytest.mark.asyncio
async def test_unrelated_question_below_threshold_returns_no_match():
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_answer_memory(embedding=[1.0, 0.0, 0.0]))
    embedding_client = TextKeyedEmbeddingClient(
        vectors={"What is your desired salary?": [0.0, 1.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )

    result = await FindSimilarAnswer(repo, embedding_client).execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="What is your desired salary?"
        )
    )

    assert result is None


@pytest.mark.asyncio
async def test_threshold_is_tunable_per_call():
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(_answer_memory(embedding=[1.0, 0.0, 0.0]))
    # A moderately related question — similarity lands below the default
    # threshold but above a deliberately loosened one.
    embedding_client = TextKeyedEmbeddingClient(
        vectors={"related question": [1.0, 1.0, 0.0]},
        default=[1.0, 1.0, 0.0],
    )
    use_case = FindSimilarAnswer(repo, embedding_client)

    default_result = await use_case.execute(
        FindSimilarAnswerInput(user_id="user-1", question_text="related question")
    )
    assert default_result is None

    loosened_result = await use_case.execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="related question", threshold=0.5
        )
    )
    assert loosened_result is not None
    assert loosened_result.answer.id == "am-1"


@pytest.mark.asyncio
async def test_scoped_to_requesting_user():
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(
        _answer_memory(id="am-other-user", user_id="user-2", embedding=[1.0, 0.0, 0.0])
    )
    embedding_client = TextKeyedEmbeddingClient(vectors={}, default=[1.0, 0.0, 0.0])

    result = await FindSimilarAnswer(repo, embedding_client).execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="Why do you want to work here?"
        )
    )

    assert result is None


@pytest.mark.asyncio
async def test_picks_the_closest_match_among_multiple_candidates():
    repo = InMemoryAnswerMemoryRepo()
    await repo.add(
        _answer_memory(
            id="am-close",
            question_text="Why do you want to work here?",
            answer_text="Because of the mission.",
            embedding=[1.0, 0.0, 0.0],
        )
    )
    await repo.add(
        _answer_memory(
            id="am-further",
            question_text="Are you willing to relocate?",
            answer_text="Yes, within the US.",
            embedding=[0.9, 0.3, 0.0],
        )
    )
    embedding_client = TextKeyedEmbeddingClient(vectors={}, default=[1.0, 0.0, 0.0])

    result = await FindSimilarAnswer(repo, embedding_client).execute(
        FindSimilarAnswerInput(
            user_id="user-1", question_text="What interests you about this role?"
        )
    )

    assert result is not None
    assert result.answer.id == "am-close"
