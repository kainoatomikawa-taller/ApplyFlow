"""Tests for ProvenanceFactAssembler — the one definition of "what may we
assert about this candidate" that both generation flows read from.
"""

from __future__ import annotations

import pytest

from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.exceptions import ProfileNotFoundError
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    StubAnswerMemoryRepository,
    StubProfileRepository,
)


@pytest.mark.asyncio
async def test_profile_facts_keep_the_sources_the_data_model_records(profile):
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )

    facts = await assembler.assemble("user-1")

    by_text = {fact.text: fact.source for fact in facts}
    assert by_text["Name: Dana Reyes"] is ProvenanceSource.USER_ENTERED
    assert by_text["Skill: Python"] is ProvenanceSource.PARSED_RESUME


@pytest.mark.asyncio
async def test_remembered_answers_join_the_corpus_as_answer_provenance(
    profile, answer_memory
):
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )

    facts = await assembler.assemble("user-1")

    answer_facts = [fact for fact in facts if fact.source is ProvenanceSource.ANSWER]
    assert len(answer_facts) == 1
    assert "Have you led a team?" in answer_facts[0].text
    assert "I led a team of 5 engineers." in answer_facts[0].text


@pytest.mark.asyncio
async def test_another_users_answers_never_enter_this_candidates_corpus(
    profile, answer_memory
):
    other_user_memory = type(answer_memory)(
        id="mem-2",
        user_id="user-2",
        question_text="Have you shipped a compiler?",
        answer_text="Yes, at Initech.",
        embedding=[0.3],
        source=ProvenanceSource.ANSWER,
    )
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository(
            [answer_memory, other_user_memory]
        ),
    )

    facts = await assembler.assemble("user-1")

    assert not any("Initech" in fact.text for fact in facts)


@pytest.mark.asyncio
async def test_a_user_with_no_profile_has_no_corpus_to_generate_from():
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(None),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )

    with pytest.raises(ProfileNotFoundError):
        await assembler.assemble("user-1")


@pytest.mark.asyncio
async def test_every_assembled_fact_carries_a_real_provenance_source(
    profile, answer_memory
):
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )

    facts = await assembler.assemble("user-1")

    assert facts
    assert all(isinstance(fact.source, ProvenanceSource) for fact in facts)
    assert all(fact.text.strip() for fact in facts)
