"""Answer-memory use case tests using in-memory fakes for the ports/repository.

Demonstrates the application layer depends only on abstractions: no real
embedding provider or database is required to test it.
"""

import pytest

from src.application.dtos.answer_memory_dtos import StoreAnswerInput
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.use_cases.get_answer_memory import GetAnswerMemory
from src.application.use_cases.list_answer_memories import ListAnswerMemories
from src.application.use_cases.store_answer import StoreAnswer
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.exceptions import AnswerMemoryNotFoundError
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


class FakeEmbeddingClient(EmbeddingClientPort):
    def __init__(self, embedding: list[float] | None = None) -> None:
        self.embedding = embedding if embedding is not None else [0.1, 0.2, 0.3]
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embedding


class SequentialIdGenerator(IdGeneratorPort):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next}"


def _store_input(**overrides) -> StoreAnswerInput:
    defaults: dict = dict(
        user_id="user-1",
        question_text="Are you willing to relocate?",
        answer_text="Yes, within the US.",
    )
    defaults.update(overrides)
    return StoreAnswerInput(**defaults)


@pytest.mark.asyncio
async def test_store_answer_persists_with_embedding_and_answer_provenance():
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = FakeEmbeddingClient(embedding=[0.5, 0.6])

    output = await StoreAnswer(
        repository=repo,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    ).execute(_store_input())

    assert output.id == "id-1"
    assert output.question_text == "Are you willing to relocate?"
    assert output.answer_text == "Yes, within the US."
    assert output.embedding == [0.5, 0.6]
    assert output.source == ProvenanceSource.ANSWER.value

    stored = repo.store["id-1"]
    assert stored.embedding == [0.5, 0.6]
    assert stored.source is ProvenanceSource.ANSWER


@pytest.mark.asyncio
async def test_store_answer_embeds_the_question_text_not_the_answer():
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = FakeEmbeddingClient()

    await StoreAnswer(
        repository=repo,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    ).execute(
        _store_input(
            question_text="What's your desired salary?", answer_text="$150k"
        )
    )

    assert embedding_client.calls == ["What's your desired salary?"]


@pytest.mark.asyncio
async def test_get_answer_memory_returns_owners_record():
    repo = InMemoryAnswerMemoryRepo()
    uploaded = await StoreAnswer(
        repository=repo,
        embedding_client=FakeEmbeddingClient(),
        id_generator=SequentialIdGenerator(),
    ).execute(_store_input(user_id="user-1"))

    output = await GetAnswerMemory(repo).execute(uploaded.id, "user-1")
    assert output.id == uploaded.id


@pytest.mark.asyncio
async def test_get_answer_memory_hides_another_users_record_as_not_found():
    repo = InMemoryAnswerMemoryRepo()
    uploaded = await StoreAnswer(
        repository=repo,
        embedding_client=FakeEmbeddingClient(),
        id_generator=SequentialIdGenerator(),
    ).execute(_store_input(user_id="user-1"))

    with pytest.raises(AnswerMemoryNotFoundError):
        await GetAnswerMemory(repo).execute(uploaded.id, "someone-else")


@pytest.mark.asyncio
async def test_get_answer_memory_raises_for_unknown_id():
    repo = InMemoryAnswerMemoryRepo()
    with pytest.raises(AnswerMemoryNotFoundError):
        await GetAnswerMemory(repo).execute("does-not-exist", "user-1")


@pytest.mark.asyncio
async def test_list_answer_memories_scopes_to_requesting_user():
    repo = InMemoryAnswerMemoryRepo()
    use_case = StoreAnswer(
        repository=repo,
        embedding_client=FakeEmbeddingClient(),
        id_generator=SequentialIdGenerator(),
    )
    await use_case.execute(_store_input(user_id="user-1"))
    await use_case.execute(_store_input(user_id="user-2"))

    outputs = await ListAnswerMemories(repo).execute("user-1")
    assert len(outputs) == 1
    assert outputs[0].user_id == "user-1"
