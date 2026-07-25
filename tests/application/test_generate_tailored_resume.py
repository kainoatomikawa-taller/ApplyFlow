"""Tests for GenerateTailoredResume — generate, then guard, then return.

The behavior under test is not "does it call an LLM" but "can an
unsupported claim reach a caller". Shared fakes live in `conftest.py`.
"""

from __future__ import annotations

import logging

import pytest

from src.application.dtos.generation_dtos import GenerateTailoredResumeInput
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from tests.application.conftest import (
    RecordingGenerator,
    StubAnswerMemoryRepository,
    StubJobPostingRepository,
    StubProfileRepository,
)

_INPUT = GenerateTailoredResumeInput(user_id="user-1", job_posting_id="job-posting-1")


def _use_case(posting, fact_assembler, generator) -> GenerateTailoredResume:
    return GenerateTailoredResume(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        generator=generator,
    )


@pytest.mark.asyncio
async def test_supported_lines_are_returned_and_traced_to_their_provenance(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)\n"
        "Built payment services in Python."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == (
        "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)\n"
        "Built payment services in Python."
    )
    assert result.violations == []
    assert result.backing_sources == ["parsed_resume"]
    assert result.document_kind == "tailored_resume"
    assert result.job_posting_id == "job-posting-1"


@pytest.mark.asyncio
async def test_a_fabricated_employer_never_reaches_the_caller(posting, fact_assembler):
    generator = RecordingGenerator(
        "Built payment services in Python.\nStaff Engineer at Initech (2016-2019)"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == "Built payment services in Python."
    assert "Initech" not in result.content
    assert [v.line for v in result.violations] == [
        "Staff Engineer at Initech (2016-2019)"
    ]
    assert "initech" in result.violations[0].unsupported_terms


@pytest.mark.asyncio
async def test_a_requirement_the_candidate_cannot_back_is_not_claimed(
    posting, fact_assembler
):
    """The posting requires Terraform and the model obliged. Requirements
    reach the generator but never the guard, so the claim is stripped
    instead of validating itself."""
    generator = RecordingGenerator("Skills: Python\nExpert in Terraform at scale.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "Terraform" in generator.requirements
    assert result.content == "Skills: Python"
    assert "terraform" in result.violations[0].unsupported_terms


@pytest.mark.asyncio
async def test_the_generator_receives_the_facts_and_the_requirements(
    posting, fact_assembler
):
    generator = RecordingGenerator("Skills: Python")

    await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert generator.job_title == "Senior Platform Engineer"
    assert generator.company == "Globex"
    assert generator.requirements == ("Python", "Terraform")
    assert "Skill: Python" in generator.facts
    assert any("Acme Corp" in fact for fact in generator.facts)


@pytest.mark.asyncio
async def test_an_answer_backed_claim_survives_and_is_credited_to_the_answer(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    generator = RecordingGenerator("Led a team of 5 engineers.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == "Led a team of 5 engineers."
    assert "answer" in result.backing_sources


@pytest.mark.asyncio
async def test_an_inflated_number_is_stripped_even_though_the_claim_is_real(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    generator = RecordingGenerator("Led a team of 25 engineers.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == ""
    assert result.violations[0].unsupported_terms == ["25"]


@pytest.mark.asyncio
async def test_violations_are_logged_with_the_terms_that_failed(
    posting, fact_assembler, caplog
):
    generator = RecordingGenerator("Staff Engineer at Initech (2016-2019)")

    with caplog.at_level(logging.WARNING):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    logged = caplog.text
    assert "provenance guard stripped 1 unsupported line(s)" in logged
    assert "tailored_resume" in logged
    assert "user-1" in logged
    assert "job-posting-1" in logged
    assert "initech" in logged
    assert "Staff Engineer at Initech (2016-2019)" in logged


@pytest.mark.asyncio
async def test_a_clean_run_logs_nothing_at_warning_level(
    posting, fact_assembler, caplog
):
    generator = RecordingGenerator("Skills: Python")

    with caplog.at_level(logging.WARNING):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert caplog.records == []


@pytest.mark.asyncio
async def test_a_missing_posting_raises_before_anything_is_generated(fact_assembler):
    generator = RecordingGenerator("Skills: Python")
    use_case = _use_case(None, fact_assembler, generator)

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(_INPUT)

    assert generator.facts == ()


@pytest.mark.asyncio
async def test_a_missing_profile_raises_rather_than_writing_from_nothing(posting):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(None),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )
    generator = RecordingGenerator("Skills: Python")

    with pytest.raises(ProfileNotFoundError):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert generator.facts == ()
