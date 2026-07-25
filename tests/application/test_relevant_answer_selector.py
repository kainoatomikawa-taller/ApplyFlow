"""Tests for RelevantAnswerSelector — which of a candidate's remembered
answers a given job's letter should be built around.

The behaviors that matter: relevance actually filters, the ranking is by
relevance, the bar is the loose one (a job requirement is never phrased like
the question it relates to), scope stays per-user, and "nothing relevant" is
an ordinary answer rather than an error.
"""

from __future__ import annotations

import pytest

from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.services.relevant_answer_selector import (
    DEFAULT_LIMIT,
    RelevantAnswerSelector,
)
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import StubAnswerMemoryRepository

#: Orthogonal topic axes: an answer about a topic and a query about the same
#: topic land on the same axis, different topics score 0.0.
_TOPICS = {
    "leadership": [1.0, 0.0, 0.0],
    "kubernetes": [0.0, 1.0, 0.0],
    "retail": [0.0, 0.0, 1.0],
}


class TopicEmbeddingClient(EmbeddingClientPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        lowered = text.lower()
        for topic, vector in _TOPICS.items():
            if topic in lowered:
                return list(vector)
        return [0.1, 0.1, 0.1]


def _answer(memory_id: str, question: str, answer: str, topic: str) -> AnswerMemory:
    return AnswerMemory(
        id=memory_id,
        user_id="user-1",
        question_text=question,
        answer_text=answer,
        embedding=list(_TOPICS[topic]),
        source=ProvenanceSource.ANSWER,
    )


_LEADERSHIP = _answer(
    "mem-lead",
    "Have you led a team?",
    "Yes, I led a team of 5 engineers.",
    "leadership",
)
_RETAIL = _answer(
    "mem-retail",
    "Are you willing to work weekends?",
    "Yes, I worked retail weekends for two years.",
    "retail",
)


def _selector(
    memories: list[AnswerMemory], client: TopicEmbeddingClient | None = None
) -> tuple[RelevantAnswerSelector, TopicEmbeddingClient]:
    embedding_client = client or TopicEmbeddingClient()
    return (
        RelevantAnswerSelector(
            answer_memory_repository=StubAnswerMemoryRepository(memories),
            embedding_client=embedding_client,
        ),
        embedding_client,
    )


@pytest.mark.asyncio
async def test_only_answers_relevant_to_the_job_are_selected():
    selector, _ = _selector([_LEADERSHIP, _RETAIL])

    selected = await selector.select(
        user_id="user-1", query="Senior Platform Engineer leadership experience"
    )

    assert len(selected) == 1
    assert "led a team of 5 engineers" in selected[0].text


@pytest.mark.asyncio
async def test_a_selected_answer_keeps_its_answer_provenance():
    selector, _ = _selector([_LEADERSHIP])

    selected = await selector.select(user_id="user-1", query="leadership")

    assert selected[0].source is ProvenanceSource.ANSWER


@pytest.mark.asyncio
async def test_the_question_travels_with_the_answer():
    """ "Five engineers" only means something next to what was asked."""
    selector, _ = _selector([_LEADERSHIP])

    selected = await selector.select(user_id="user-1", query="leadership")

    assert "Have you led a team?" in selected[0].text


@pytest.mark.asyncio
async def test_answers_are_ranked_with_the_most_relevant_first():
    exact = _answer("mem-exact", "Led a team?", "Yes.", "leadership")
    partial = AnswerMemory(
        id="mem-partial",
        user_id="user-1",
        question_text="Managed anyone?",
        answer_text="Some mentoring.",
        embedding=[0.8, 0.3, 0.0],
        source=ProvenanceSource.ANSWER,
    )
    selector, _ = _selector([partial, exact])

    selected = await selector.select(user_id="user-1", query="leadership")

    assert "Yes." in selected[0].text
    assert "Some mentoring." in selected[1].text


@pytest.mark.asyncio
async def test_selection_is_capped_so_answers_cannot_crowd_out_the_facts():
    memories = [
        _answer(f"mem-{index}", f"Q{index}", f"A{index}", "leadership")
        for index in range(DEFAULT_LIMIT + 2)
    ]
    selector, _ = _selector(memories)

    selected = await selector.select(user_id="user-1", query="leadership")

    assert len(selected) == DEFAULT_LIMIT


@pytest.mark.asyncio
async def test_an_explicit_limit_is_honored():
    memories = [
        _answer(f"mem-{index}", f"Q{index}", f"A{index}", "leadership")
        for index in range(3)
    ]
    selector, _ = _selector(memories)

    selected = await selector.select(user_id="user-1", query="leadership", limit=1)

    assert len(selected) == 1


@pytest.mark.asyncio
async def test_nothing_relevant_on_file_is_an_empty_selection_not_an_error():
    selector, _ = _selector([_RETAIL])

    selected = await selector.select(user_id="user-1", query="kubernetes")

    assert selected == ()


@pytest.mark.asyncio
async def test_a_candidate_with_no_answers_costs_no_embedding_call():
    selector, client = _selector([])

    selected = await selector.select(user_id="user-1", query="leadership")

    assert selected == ()
    assert client.calls == []


@pytest.mark.asyncio
async def test_a_zero_limit_costs_no_embedding_call():
    selector, client = _selector([_LEADERSHIP])

    selected = await selector.select(user_id="user-1", query="leadership", limit=0)

    assert selected == ()
    assert client.calls == []


@pytest.mark.asyncio
async def test_the_jobs_own_words_are_what_gets_embedded():
    selector, client = _selector([_LEADERSHIP])

    await selector.select(user_id="user-1", query="Platform Engineer leadership")

    assert client.calls == ["Platform Engineer leadership"]


@pytest.mark.asyncio
async def test_another_users_answers_are_never_selected():
    other = AnswerMemory(
        id="mem-other",
        user_id="user-2",
        question_text="Have you led a team?",
        answer_text="Yes, at Initech.",
        embedding=list(_TOPICS["leadership"]),
        source=ProvenanceSource.ANSWER,
    )
    selector, _ = _selector([other])

    selected = await selector.select(user_id="user-1", query="leadership")

    assert selected == ()


@pytest.mark.asyncio
async def test_a_stricter_threshold_can_be_demanded_per_call():
    partial = AnswerMemory(
        id="mem-partial",
        user_id="user-1",
        question_text="Managed anyone?",
        answer_text="Some mentoring.",
        embedding=[1.0, 1.0, 0.0],  # cosine 0.707 against the leadership axis
        source=ProvenanceSource.ANSWER,
    )
    selector, _ = _selector([partial])

    assert await selector.select(user_id="user-1", query="leadership") != ()
    assert (
        await selector.select(user_id="user-1", query="leadership", threshold=0.9) == ()
    )
