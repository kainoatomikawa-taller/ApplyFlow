"""Tests for GenerateTailoredResume — generate, then guard, then return.

The behavior under test is not "does it call an LLM" but "can an
unsupported claim reach a caller". Shared fakes live in `conftest.py`.
"""

from __future__ import annotations

import logging

import pytest

from src.application.dtos.generation_dtos import GenerateTailoredResumeInput
from src.application.exceptions import (
    DocumentRenderError,
    UnattestedGenerationError,
)
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    RecordingGenerator,
    RecordingPdfRenderer,
    SequentialIdGenerator,
    StubAnswerMemoryRepository,
    StubJobPostingRepository,
    StubProfileRepository,
)

_INPUT = GenerateTailoredResumeInput(user_id="user-1", job_posting_id="job-posting-1")


def _use_case(
    posting, fact_assembler, generator, renderer=None, archive=None
) -> GenerateTailoredResume:
    return GenerateTailoredResume(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        generator=generator,
        pdf_renderer=renderer or RecordingPdfRenderer(),
        archive=archive
        or ApplicationDocumentArchive(
            repository=InMemoryApplicationDocumentRepository(),
            id_generator=SequentialIdGenerator(),
        ),
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

    assert result.document.content == (
        "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)\n"
        "Built payment services in Python."
    )
    assert result.document.violations == []
    assert result.document.backing_sources == ["parsed_resume"]
    assert result.document.document_kind == "tailored_resume"
    assert result.document.job_posting_id == "job-posting-1"


@pytest.mark.asyncio
async def test_a_fabricated_employer_never_reaches_the_caller(posting, fact_assembler):
    generator = RecordingGenerator(
        "Built payment services in Python.\nStaff Engineer at Initech (2016-2019)"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.document.content == "Built payment services in Python."
    assert "Initech" not in result.document.content
    assert [v.line for v in result.document.violations] == [
        "Staff Engineer at Initech (2016-2019)"
    ]
    assert "initech" in result.document.violations[0].unsupported_terms


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
    assert result.document.content == "Skills: Python"
    assert "terraform" in result.document.violations[0].unsupported_terms


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

    assert result.document.content == "Led a team of 5 engineers."
    assert "answer" in result.document.backing_sources


@pytest.mark.asyncio
async def test_an_inflated_number_is_stripped_even_though_the_claim_is_real(
    posting, profile, answer_memory
):
    fact_assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository([answer_memory]),
    )
    generator = RecordingGenerator(
        "Built payment services in Python.\nLed a team of 25 engineers."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.document.content == "Built payment services in Python."
    assert result.document.violations[0].unsupported_terms == ["25"]


@pytest.mark.asyncio
async def test_violations_are_logged_with_the_terms_that_failed(
    posting, fact_assembler, caplog
):
    generator = RecordingGenerator(
        "Built payment services in Python.\nStaff Engineer at Initech (2016-2019)"
    )

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


# ---- ATS-safe formatting and post-guard coherence ---------------------------


@pytest.mark.asyncio
async def test_markdown_and_glyphs_are_flattened_before_the_resume_is_returned(
    posting, fact_assembler
):
    """An ATS reads plain text, so what the model dressed up gets undressed
    — and it happens before guarding, so the text validated is the text
    returned."""
    generator = RecordingGenerator(
        "## EXPERIENCE\n"
        "**Backend Engineer** at Acme Corp\n"
        "• Built *payment* services in `Python`\n"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.document.content == (
        "EXPERIENCE\n"
        "Backend Engineer at Acme Corp\n"
        "- Built payment services in Python"
    )
    assert result.document.violations == []


@pytest.mark.asyncio
async def test_a_table_is_flattened_rather_than_shipped_to_a_parser(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "EXPERIENCE\n| Backend Engineer | Acme Corp |\n| --- | --- |"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "|" not in result.document.content
    assert "Backend Engineer Acme Corp" in result.document.content


@pytest.mark.asyncio
async def test_a_section_the_guard_emptied_is_not_left_as_a_hollow_heading(
    posting, fact_assembler
):
    """The guard strips the fabricated schooling; leaving "EDUCATION" over
    nothing would read as broken rather than shorter."""
    generator = RecordingGenerator(
        "EXPERIENCE\n"
        "Built payment services in Python.\n"
        "\n"
        "EDUCATION\n"
        "PhD in Distributed Systems, Initech Institute\n"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.document.content == "EXPERIENCE\nBuilt payment services in Python."
    assert "EDUCATION" not in result.document.content
    assert result.document.violations[0].line.startswith("PhD in Distributed Systems")


@pytest.mark.asyncio
async def test_a_section_that_kept_its_body_keeps_its_heading(posting, fact_assembler):
    generator = RecordingGenerator("SKILLS\nPython\n\nEXPERIENCE\nAcme Corp")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.document.content == "SKILLS\nPython\n\nEXPERIENCE\nAcme Corp"


@pytest.mark.asyncio
async def test_a_resume_with_nothing_attested_left_is_rejected_not_returned(
    posting, fact_assembler
):
    """Everything the model claimed was fabricated. A page of bare headings
    is not a resume, so the caller is told rather than handed one."""
    generator = RecordingGenerator(
        "EXPERIENCE\n"
        "Staff Engineer at Initech (2016-2019)\n"
        "\n"
        "EDUCATION\n"
        "PhD in Distributed Systems, Initech Institute\n"
    )

    with pytest.raises(UnattestedGenerationError) as exc_info:
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert exc_info.value.document_kind == "tailored_resume"
    assert "initech" in exc_info.value.unsupported_terms
    assert "tailored_resume" in str(exc_info.value)


@pytest.mark.asyncio
async def test_a_rejected_resume_is_still_logged_for_debugging(
    posting, fact_assembler, caplog
):
    """The audit record is written before the rejection, so the worst case
    is the best documented."""
    generator = RecordingGenerator("PhD in Distributed Systems, Initech Institute")

    with caplog.at_level(logging.WARNING), pytest.raises(UnattestedGenerationError):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert "provenance violation" in caplog.text
    assert "initech" in caplog.text


@pytest.mark.asyncio
async def test_headings_alone_do_not_count_as_attested_content(posting, fact_assembler):
    """Section headings survive guarding by asserting nothing — which is
    exactly why they cannot stand in for a resume."""
    generator = RecordingGenerator("SUMMARY\n\nEXPERIENCE\n\nSKILLS")

    with pytest.raises(UnattestedGenerationError):
        await _use_case(posting, fact_assembler, generator).execute(_INPUT)


# ---- exports: text, structure, and PDF from one guarded text ----------------


@pytest.mark.asyncio
async def test_the_text_export_is_the_guarded_text_itself(posting, fact_assembler):
    generator = RecordingGenerator("EXPERIENCE\nBuilt payment services in Python.")

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.exports.text == result.document.content


@pytest.mark.asyncio
async def test_the_pdf_is_rendered_from_the_guarded_text_not_the_draft(
    posting, fact_assembler
):
    """The renderer must never see the raw draft: the fabricated line is
    absent from what it is handed."""
    renderer = RecordingPdfRenderer(pdf=b"%PDF-1.4 rendered")
    generator = RecordingGenerator(
        "Built payment services in Python.\nStaff Engineer at Initech (2016-2019)"
    )

    result = await _use_case(posting, fact_assembler, generator, renderer).execute(
        _INPUT
    )

    assert renderer.content == "Built payment services in Python."
    assert "Initech" not in (renderer.content or "")
    assert result.exports.pdf == b"%PDF-1.4 rendered"


@pytest.mark.asyncio
async def test_the_pdf_title_names_the_role_and_company_it_was_tailored_for(
    posting, fact_assembler
):
    renderer = RecordingPdfRenderer()
    generator = RecordingGenerator("Skills: Python")

    await _use_case(posting, fact_assembler, generator, renderer).execute(_INPUT)

    assert renderer.title == "Resume - Senior Platform Engineer - Globex"


@pytest.mark.asyncio
async def test_the_structured_export_splits_the_resume_into_sections(
    posting, fact_assembler
):
    generator = RecordingGenerator(
        "Dana Reyes\n"
        "dana@example.com\n"
        "\n"
        "EXPERIENCE\n"
        "Backend Engineer at Acme Corp\n"
        "Built payment services in Python.\n"
        "\n"
        "SKILLS\n"
        "Python"
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    exports = result.exports
    assert exports.contact_lines == ["Dana Reyes", "dana@example.com"]
    assert [section.heading for section in exports.sections] == [
        "EXPERIENCE",
        "SKILLS",
    ]
    assert exports.sections[0].lines == [
        "Backend Engineer at Acme Corp",
        "Built payment services in Python.",
    ]
    assert exports.sections[1].lines == ["Python"]


@pytest.mark.asyncio
async def test_a_stripped_line_is_absent_from_every_export(posting, fact_assembler):
    """One guarded text feeds all three artifacts, so a fabrication cannot
    survive in one of them."""
    renderer = RecordingPdfRenderer()
    generator = RecordingGenerator(
        "EXPERIENCE\n"
        "Built payment services in Python.\n"
        "Staff Engineer at Initech (2016-2019)"
    )

    result = await _use_case(posting, fact_assembler, generator, renderer).execute(
        _INPUT
    )

    section_lines = [
        line for section in result.exports.sections for line in section.lines
    ]
    assert "Initech" not in result.exports.text
    assert not any("Initech" in line for line in section_lines)
    assert "Initech" not in (renderer.content or "")


@pytest.mark.asyncio
async def test_a_clean_resume_reports_no_ats_safety_violations(posting, fact_assembler):
    generator = RecordingGenerator(
        "Dana Reyes\n\nEXPERIENCE\nBuilt payment services in Python."
    )

    result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.ats_safety_violations == []


@pytest.mark.asyncio
async def test_the_finished_resume_is_validated_and_findings_are_reported(
    posting, fact_assembler, caplog
):
    """The formatter strips markdown before guarding, so a finding here would
    be a formatter gap. This proves the check runs on the finished text and
    that a finding would surface rather than pass silently."""
    generator = RecordingGenerator("EXPERIENCE\nBuilt payment services in Python.")

    with caplog.at_level(logging.DEBUG):
        result = await _use_case(posting, fact_assembler, generator).execute(_INPUT)

    assert result.ats_safety_violations == []
    assert "ats safety check passed" in caplog.text


@pytest.mark.asyncio
async def test_an_ats_violation_is_reported_and_logged_as_a_pipeline_defect(
    posting, fact_assembler, caplog
):
    """Driven through a stub validator, since the formatter makes a real one
    impossible to trigger — which is the point of having both."""
    from src.domain.services.ats_safety_validator import (
        AtsSafetyReport,
        AtsSafetyViolation,
    )

    class _StubValidator:
        def validate(self, content):
            return AtsSafetyReport(
                violations=(
                    AtsSafetyViolation(
                        rule="table_markup",
                        detail="Pipes read as table cells.",
                        line="| a | b |",
                        line_number=2,
                    ),
                )
            )

    use_case = GenerateTailoredResume(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        generator=RecordingGenerator("Built payment services in Python."),
        pdf_renderer=RecordingPdfRenderer(),
        archive=ApplicationDocumentArchive(
            repository=InMemoryApplicationDocumentRepository(),
            id_generator=SequentialIdGenerator(),
        ),
        ats_validator=_StubValidator(),
    )

    with caplog.at_level(logging.WARNING):
        result = await use_case.execute(_INPUT)

    assert [v.rule for v in result.ats_safety_violations] == ["table_markup"]
    assert result.ats_safety_violations[0].line_number == 2
    assert "ats safety check found 1 issue(s)" in caplog.text
    assert "table_markup" in caplog.text


@pytest.mark.asyncio
async def test_nothing_is_rendered_when_the_resume_is_rejected(posting, fact_assembler):
    """An unattested resume raises before any file is produced — no PDF of a
    document we refuse to stand behind."""
    renderer = RecordingPdfRenderer()
    generator = RecordingGenerator("Staff Engineer at Initech (2016-2019)")

    with pytest.raises(UnattestedGenerationError):
        await _use_case(posting, fact_assembler, generator, renderer).execute(_INPUT)

    assert renderer.calls == 0


# ---- the sent resume is archived exactly as produced ------------------------


@pytest.mark.asyncio
async def test_the_resume_that_was_returned_is_the_one_that_was_stored(
    posting, fact_assembler, document_repository, archive
):
    """Not "a resume was stored" but "the stored bytes are the returned
    bytes" — anything looser and the tracker shows something the candidate
    never sent."""
    generator = RecordingGenerator(
        "EXPERIENCE\nBuilt payment services in Python.\n"
        "Staff Engineer at Initech (2016-2019)"
    )

    result = await _use_case(
        posting, fact_assembler, generator, archive=archive
    ).execute(_INPUT)

    stored = document_repository.documents[0]
    assert stored.content == result.document.content
    assert stored.content == result.exports.text
    # The fabrication the guard removed is absent from the archive too: the
    # archive is fed post-guard text, never the draft.
    assert "Initech" not in stored.content


@pytest.mark.asyncio
async def test_the_snapshot_is_labeled_with_the_job_the_user_and_the_kind(
    posting, fact_assembler, document_repository, archive
):
    generator = RecordingGenerator("Skills: Python")

    await _use_case(posting, fact_assembler, generator, archive=archive).execute(_INPUT)

    stored = document_repository.documents[0]
    assert stored.user_id == "user-1"
    assert stored.job_posting_id == "job-posting-1"
    assert stored.document_kind is GeneratedDocumentKind.TAILORED_RESUME
    assert stored.backing_sources == (ProvenanceSource.PARSED_RESUME,)


@pytest.mark.asyncio
async def test_the_caller_is_told_which_snapshot_holds_what_it_just_received(
    posting, fact_assembler, document_repository, archive
):
    generator = RecordingGenerator("Skills: Python")

    result = await _use_case(
        posting, fact_assembler, generator, archive=archive
    ).execute(_INPUT)

    assert result.document.document_id == document_repository.documents[0].id
    assert result.document.version == 1


@pytest.mark.asyncio
async def test_regenerating_for_the_same_job_adds_a_version_and_keeps_the_old_one(
    posting, fact_assembler, document_repository, archive
):
    """The earlier resume may already have been sent, so it stays readable."""
    first = await _use_case(
        posting, fact_assembler, RecordingGenerator("Skills: Python"), archive=archive
    ).execute(_INPUT)
    second = await _use_case(
        posting,
        fact_assembler,
        RecordingGenerator("EXPERIENCE\nBuilt payment services in Python."),
        archive=archive,
    ).execute(_INPUT)

    assert [d.version for d in document_repository.documents] == [1, 2]
    assert first.document.version == 1
    assert second.document.version == 2
    assert document_repository.documents[0].content == "Skills: Python"
    assert first.document.document_id != second.document.document_id


@pytest.mark.asyncio
async def test_a_rejected_resume_is_never_archived(
    posting, fact_assembler, document_repository, archive
):
    """Nothing attested survived, so there is no document to record — a
    snapshot of a refused draft would misrepresent it as sent."""
    generator = RecordingGenerator("Staff Engineer at Initech (2016-2019)")

    with pytest.raises(UnattestedGenerationError):
        await _use_case(posting, fact_assembler, generator, archive=archive).execute(
            _INPUT
        )

    assert document_repository.documents == []


@pytest.mark.asyncio
async def test_nothing_is_archived_when_the_posting_does_not_exist(
    fact_assembler, document_repository, archive
):
    generator = RecordingGenerator("Skills: Python")
    use_case = _use_case(None, fact_assembler, generator, archive=archive)

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(_INPUT)

    assert document_repository.documents == []


@pytest.mark.asyncio
async def test_a_resume_whose_pdf_fails_to_render_is_never_archived(
    posting, fact_assembler, document_repository, archive
):
    """It was never handed to the candidate, so recording it as sent would be
    a false statement."""

    class _FailingRenderer(RecordingPdfRenderer):
        def render(self, content, *, title):
            raise DocumentRenderError("no font available")

    use_case = _use_case(
        posting,
        fact_assembler,
        RecordingGenerator("Skills: Python"),
        _FailingRenderer(),
        archive,
    )

    with pytest.raises(DocumentRenderError):
        await use_case.execute(_INPUT)

    assert document_repository.documents == []
