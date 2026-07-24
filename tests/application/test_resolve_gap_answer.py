"""Tests for ResolveGapAnswer — captures a candidate's response to a
gap-resolution question, or cleanly omits the gap when they decline.
"""

from __future__ import annotations

import pytest

from src.application.dtos.gap_resolution_dtos import ResolveGapAnswerInput
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.use_cases.resolve_gap_answer import ResolveGapAnswer
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


class FakeEmbeddingClient(EmbeddingClientPort):
    def __init__(self, embedding: list[float] | None = None) -> None:
        self.embedding = embedding if embedding is not None else [0.1, 0.2]
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


def _input(**overrides: object) -> ResolveGapAnswerInput:
    defaults: dict[str, object] = dict(
        user_id="user-1",
        gap="Leadership experience preferred",
        question_text="Have you ever led a team, run a project, or mentored someone?",
        answer_text="Yes, I led a team of 5 engineers for two years.",
    )
    defaults.update(overrides)
    return ResolveGapAnswerInput(**defaults)


@pytest.mark.asyncio
async def test_genuine_answer_is_captured_as_an_answer_memory():
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = FakeEmbeddingClient(embedding=[0.5, 0.6])
    use_case = ResolveGapAnswer(
        repository=repo,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    )

    result = await use_case.execute(_input())

    assert result.captured is True
    assert result.gap == "Leadership experience preferred"
    assert result.answer_memory_id == "id-1"
    stored = repo.store["id-1"]
    assert stored.user_id == "user-1"
    assert stored.answer_text == "Yes, I led a team of 5 engineers for two years."
    assert (
        stored.question_text
        == "Have you ever led a team, run a project, or mentored someone?"
    )
    assert stored.embedding == [0.5, 0.6]
    assert stored.source is ProvenanceSource.ANSWER


@pytest.mark.asyncio
async def test_embeds_the_question_not_the_answer():
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = FakeEmbeddingClient()
    use_case = ResolveGapAnswer(
        repository=repo,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    )

    await use_case.execute(_input())

    assert embedding_client.calls == [
        "Have you ever led a team, run a project, or mentored someone?"
    ]


@pytest.mark.asyncio
async def test_decline_response_is_omitted_without_persisting_anything():
    repo = InMemoryAnswerMemoryRepo()
    embedding_client = FakeEmbeddingClient()
    use_case = ResolveGapAnswer(
        repository=repo,
        embedding_client=embedding_client,
        id_generator=SequentialIdGenerator(),
    )

    result = await use_case.execute(_input(answer_text="Nothing to add"))

    assert result.captured is False
    assert result.answer_memory_id is None
    assert repo.store == {}
    assert embedding_client.calls == []


@pytest.mark.asyncio
async def test_blank_answer_is_treated_as_a_decline():
    repo = InMemoryAnswerMemoryRepo()
    use_case = ResolveGapAnswer(
        repository=repo,
        embedding_client=FakeEmbeddingClient(),
        id_generator=SequentialIdGenerator(),
    )

    result = await use_case.execute(_input(answer_text="   "))

    assert result.captured is False
    assert repo.store == {}


@pytest.mark.asyncio
async def test_hedged_but_genuine_answer_is_still_captured():
    repo = InMemoryAnswerMemoryRepo()
    use_case = ResolveGapAnswer(
        repository=repo,
        embedding_client=FakeEmbeddingClient(),
        id_generator=SequentialIdGenerator(),
    )

    result = await use_case.execute(
        _input(answer_text="No formal title, but I mentored two interns.")
    )

    assert result.captured is True
    assert len(repo.store) == 1
