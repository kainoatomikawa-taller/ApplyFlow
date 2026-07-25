"""Tests for GenerateCoverLetter — the same generate-then-guard contract as
`GenerateTailoredResume`, on the document where a model is most tempted to
editorialize. Shared fakes live in `conftest.py`.
"""

from __future__ import annotations

import logging

import pytest

from src.application.dtos.generation_dtos import GenerateCoverLetterInput
from src.application.exceptions import UnattestedGenerationError
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.use_cases.generate_cover_letter import GenerateCoverLetter
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact
from src.domain.value_objects.provenance_source import ProvenanceSource
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
    draft = (
        "I am applying to Globex in Austin, TX.\nI built payment services in Python."
    )
    generator = RecordingGenerator(draft)

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    # The posting-naming line survives on the posting's own terms; only the
    # second line claims anything, and only it needs provenance.
    assert result.content == draft
    assert result.backing_sources == ["parsed_resume"]


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
        "I built payment services in Python.\n"
        "I have used Terraform to manage infrastructure for years."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "Terraform" in generator.requirements
    assert result.content == "I built payment services in Python."
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
    generator = RecordingGenerator(
        "I built payment services in Python.\n" "I am a seasoned Kubernetes architect."
    )

    with caplog.at_level(logging.WARNING):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    logged = caplog.text
    assert "cover_letter" in logged
    assert "provenance violation" in logged
    assert "seasoned" in logged


@pytest.mark.asyncio
async def test_a_letter_with_nothing_attested_left_is_rejected_not_returned(
    posting, fact_assembler
):
    """Enthusiasm and a salutation pass the guard while claiming nothing, so
    the letter has to be refused rather than sent as finished work — the
    same rule the resume flow applies."""
    generator = RecordingGenerator(
        "Dear Hiring Manager,\n"
        "I am excited to apply and eager to discuss the opportunity.\n"
        "Sincerely,"
    )

    with pytest.raises(UnattestedGenerationError) as exc_info:
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert exc_info.value.document_kind == "cover_letter"


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


# ---- answer reuse and plain-text hygiene ------------------------------------


class _StubAnswerSelector:
    """Stands in for RelevantAnswerSelector: returns scripted highlights and
    records the relevance query it was given."""

    def __init__(self, facts: tuple[ProvenanceBackedFact, ...] = ()) -> None:
        self._facts = facts
        self.query: str | None = None
        self.user_id: str | None = None

    async def select(self, *, user_id, query, limit=3, threshold=None):
        self.user_id = user_id
        self.query = query
        return self._facts


def _answer_fact(text: str) -> ProvenanceBackedFact:
    return ProvenanceBackedFact(text=text, source=ProvenanceSource.ANSWER)


def _use_case_with_selector(posting, fact_assembler, generator, selector):
    return GenerateCoverLetter(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        generator=generator,
        answer_selector=selector,
    )


@pytest.mark.asyncio
async def test_relevant_answers_are_handed_to_the_generator(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    selector = _StubAnswerSelector(
        (_answer_fact("Asked 'Have you led a team?', answered: I led a team of 5."),)
    )
    generator = RecordingGenerator("I led a team of 5 engineers.")

    await _use_case_with_selector(posting, fact_assembler, generator, selector).execute(
        _INPUT
    )

    assert generator.relevant_answers == (
        "Asked 'Have you led a team?', answered: I led a team of 5.",
    )


@pytest.mark.asyncio
async def test_the_relevance_query_is_the_jobs_own_words(posting, fact_assembler):
    selector = _StubAnswerSelector()
    generator = RecordingGenerator("I built payment services in Python.")

    await _use_case_with_selector(posting, fact_assembler, generator, selector).execute(
        _INPUT
    )

    assert selector.user_id == "user-1"
    assert "Senior Platform Engineer" in selector.query
    assert "Terraform" in selector.query


@pytest.mark.asyncio
async def test_narrowing_the_highlights_never_narrows_what_the_guard_accepts(
    posting, profile, answer_memory
):
    """The selector judged nothing relevant, but the answer is still an
    attested fact — a letter built on it must not be stripped."""
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    generator = RecordingGenerator("I led a team of 5 engineers.")

    result = await _use_case_with_selector(
        posting, fact_assembler, generator, _StubAnswerSelector()
    ).execute(_INPUT)

    assert generator.relevant_answers == ()
    assert result.content == "I led a team of 5 engineers."
    assert "answer" in result.backing_sources


@pytest.mark.asyncio
async def test_the_full_fact_corpus_still_reaches_the_generator_alongside(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    selector = _StubAnswerSelector((_answer_fact("Asked 'Q', answered: A"),))
    generator = RecordingGenerator("I built payment services in Python.")

    await _use_case_with_selector(posting, fact_assembler, generator, selector).execute(
        _INPUT
    )

    assert any("Acme Corp" in fact for fact in generator.facts)
    assert any("led a team of 5 engineers" in fact for fact in generator.facts)


@pytest.mark.asyncio
async def test_a_letter_is_still_written_without_a_selector_configured(
    posting, fact_assembler
):
    """Answer highlighting needs an embedding provider; the letter does not."""
    generator = RecordingGenerator("I built payment services in Python.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert generator.relevant_answers == ()
    assert result.content == "I built payment services in Python."


@pytest.mark.asyncio
async def test_markdown_in_a_letter_is_flattened_before_it_reaches_a_reader(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "Dear Hiring Manager,\n\n"
        "I built **payment services** in `Python`.\n\n"
        "Sincerely,"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.content == (
        "Dear Hiring Manager,\n\nI built payment services in Python.\n\nSincerely,"
    )


@pytest.mark.asyncio
async def test_typographic_punctuation_in_a_letter_becomes_ascii(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "I built payment services in Python — in Austin, TX."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "—" not in result.content
    assert "Python - in Austin, TX." in result.content
