"""Tests for GenerateCoverLetter — the same generate-then-guard contract as
`GenerateTailoredResume`, on the document where a model is most tempted to
editorialize. Shared fakes live in `conftest.py`.
"""

from __future__ import annotations

import logging

import pytest

from src.application.dtos.generation_dtos import GenerateCoverLetterInput
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.use_cases.generate_cover_letter import GenerateCoverLetter
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from tests.application.conftest import (
    RecordingGenerator,
    StubAnswerMemoryRepository,
    StubJobPostingRepository,
    StubProfileRepository,
)

_INPUT = GenerateCoverLetterInput(user_id="user-1", job_posting_id="job-posting-1")


def _use_case(posting, fact_assembler, generator) -> GenerateCoverLetter:
    return GenerateCoverLetter(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        generator=generator,
    )


@pytest.mark.asyncio
async def test_a_letter_grounded_in_the_record_passes_through_intact(
    posting, fact_assembler
):
    draft = (
        "Dear Hiring Manager,\n"
        "\n"
        "I am excited to apply for the Senior Platform Engineer role at Globex.\n"
        "I worked as a Backend Engineer at Acme Corp.\n"
        "I built payment services in Python.\n"
        "\n"
        "Sincerely,\n"
        "Dana Reyes"
    )
    generator = RecordingGenerator(draft)

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == draft
    assert result.violations == []
    assert result.document_kind == "cover_letter"


@pytest.mark.asyncio
async def test_unearned_praise_is_stripped_from_the_letter(posting, fact_assembler):
    """ "Seasoned", "extensive", "industry-leading" are claims about the
    candidate's ability, and nothing in the record states them."""
    generator = RecordingGenerator(
        "I built payment services in Python.\n"
        "I am a seasoned architect with extensive distributed-systems depth."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == "I built payment services in Python."
    assert "seasoned" in result.violations[0].unsupported_terms


@pytest.mark.asyncio
async def test_naming_the_role_applied_for_is_not_treated_as_a_candidate_claim(
    posting, fact_assembler
):
    line = "I am applying to Globex in Austin, TX."
    generator = RecordingGenerator(line)

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == line
    # Named the posting, claimed nothing about the candidate — so the line
    # is credited to no provenance rather than borrowing one.
    assert result.backing_sources == []


@pytest.mark.asyncio
async def test_an_invented_metric_never_reaches_the_caller(posting, fact_assembler):
    generator = RecordingGenerator(
        "I built payment services in Python.\n"
        "My work cut checkout latency by 40% for 2 million users."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "40" not in result.content
    assert result.content == "I built payment services in Python."


@pytest.mark.asyncio
async def test_a_requirement_the_candidate_cannot_back_is_not_claimed(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "I have used Terraform to manage infrastructure for years."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "Terraform" in generator.requirements
    assert result.content == ""
    assert "terraform" in result.violations[0].unsupported_terms


@pytest.mark.asyncio
async def test_answers_given_during_gap_resolution_can_ground_the_letter(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    generator = RecordingGenerator("I led a team of 5 engineers.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    # The headcount and the leading come only from the remembered answer,
    # so the letter cannot stand without crediting that source.
    assert result.content == "I led a team of 5 engineers."
    assert "answer" in result.backing_sources


@pytest.mark.asyncio
async def test_violations_are_logged_against_the_cover_letter_flow(
    posting, fact_assembler, caplog
):
    generator = RecordingGenerator("I am a seasoned Kubernetes architect.")

    with caplog.at_level(logging.WARNING):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    logged = caplog.text
    assert "cover_letter" in logged
    assert "provenance violation" in logged
    assert "seasoned" in logged


@pytest.mark.asyncio
async def test_a_missing_posting_raises_before_anything_is_generated(fact_assembler):
    generator = RecordingGenerator("I built payment services in Python.")

    with pytest.raises(JobPostingNotFoundError):
        await _use_case(None, fact_assembler, generator).execute(_INPUT)

    assert generator.facts == ()


@pytest.mark.asyncio
async def test_a_missing_profile_raises_rather_than_writing_from_nothing(posting):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(None),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )
    generator = RecordingGenerator("I built payment services in Python.")

    with pytest.raises(ProfileNotFoundError):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert generator.facts == ()
