"""Epic 04 acceptance check — the tailoring engine's Definition of Done.

Runs the ONE flow described in `docs/epic-04-acceptance-check.md` against
REAL infrastructure (a real Postgres database, real Anthropic and OpenAI
keys, and the real HTTP app with real Supabase-JWT auth) — no fakes, no
mocks, no dependency overrides. Opt-in, like `test_epic03_matching_pipeline.py`
and the other real-infra tests in this suite, so `pytest` never touches a
real database or spends money unless a developer deliberately asks for it:

    RUN_EPIC04_ACCEPTANCE_TEST=1 pytest tests/acceptance -v -s

Requires, via `.env` or exported env vars:
    DATABASE_URL          a reachable Postgres (local `docker compose up db`
                           or a Supabase project)
    SUPABASE_JWT_SECRET    used both to mint this test's bearer token and by
                           the app to verify it, so the run proves the real
                           auth path rather than bypassing it
    ANTHROPIC_API_KEY      a pay-as-you-go key — gap detection and question
                           phrasing run on the cheap tier, the resume and
                           the cover letter on the strong tier
    OPENAI_API_KEY         the embeddings behind answer memory: the question
                           loop's "already answered" match and the cover
                           letter's answer selection (see
                           `OpenAiEmbeddingClient`)

The single flow, in order:
  1. Seed one candidate — a real record: contact details, two roles, a
     degree, four skills, U.S. citizenship, sources split across
     `user_entered` and `parsed_resume` — plus one posting that asks for
     two things the record does not back: KAFKA, which the candidate does
     in fact have and will say so, and KUBERNETES, which they do not and
     will decline. Both are asked for by the same posting on purpose: the
     engine has to turn the first into honest new material and keep the
     second out of the output entirely.
  2. `GET /api/job-postings/{id}/gaps` — the real gap detector finds both.
  3. `POST /api/gap-resolution/questions` — one neutral question per gap,
     nothing suppressed (this candidate has answered nothing yet).
  4. `POST /api/gap-resolution/answers` — the Kafka question is answered
     truthfully and captured as an `answer`-provenance fact; every other
     gap is declined and leaves no trace at all.
  5. `POST /api/gap-resolution/questions` again — the answered gap now
     comes back as `already_answered` (the memory suppresses the re-ask
     across a reworded question), while the declined ones are still asked,
     because declining is not answering.
  6. `POST /api/job-postings/{id}/tailored-resume` and
     `POST /api/job-postings/{id}/cover-letter` — both documents generate,
     and each is re-validated here, independently of the flow that made it:
     every surviving line re-checks clean against the candidate's fact
     corpus, KUBERNETES appears in neither document, and anything that does
     mention Kafka traces to the `answer` source it came from.
  7. The resume's three exports (text, structure, PDF) all say the same
     thing, its section headings are ones an ATS recognizes, and the ATS
     safety validator finds nothing.
  8. Both documents are read back through the stored-snapshot routes and
     match byte for byte, digest included.

An unauthenticated call to the generation route is checked first, so the
auth gate is proven live before a cent is spent.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import date

import jwt
import pytest
from fastapi.testclient import TestClient

from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.ats_safety_validator import (
    RULE_COLUMN_WHITESPACE,
    RULE_DECORATIVE_GLYPH,
    RULE_MARKDOWN_SYNTAX,
    RULE_TABLE_MARKUP,
    RULE_UNRENDERABLE_CHARACTER,
    AtsSafetyValidator,
)
from src.domain.services.ats_section_headings import is_standard_section_heading
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.value_objects.address import Address
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.config import get_settings
from src.infrastructure.persistence.answer_memory_repository_impl import (
    SqlAlchemyAnswerMemoryRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    dispose_engine,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
from src.interfaces.http.app import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EPIC04_ACCEPTANCE_TEST") != "1",
    reason=(
        "opt-in: set RUN_EPIC04_ACCEPTANCE_TEST=1 with DATABASE_URL, "
        "SUPABASE_JWT_SECRET, ANTHROPIC_API_KEY, and OPENAI_API_KEY "
        "configured to run the Epic 04 Definition-of-Done check (see "
        "docs/epic-04-acceptance-check.md)"
    ),
)

#: The requirement the candidate genuinely meets but whose evidence is
#: nowhere in their stored record — the gap the question loop is supposed to
#: turn into an attested fact.
_ANSWERABLE_SKILL = "Kafka"

#: The requirement the candidate does NOT meet. The posting asks for it, so
#: the generator is under exactly the pressure that produces a fabricated
#: claim; nothing in the candidate's record backs it, so it must not appear
#: in a single line of either finished document.
_DECLINED_SKILL = "Kubernetes"

#: A truthful answer, in the candidate's own words, naming only things their
#: record (or this sentence itself) already states.
_KAFKA_ANSWER = (
    "Yes - I built and ran the Kafka event pipeline that carried shipment "
    "tracking updates at Northwind Freight for about three years, including "
    "its consumer groups and replay tooling."
)

#: A decline, in one of the exact forms `GapAnswerPolicy` recognizes.
_DECLINE = "no experience"


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


def _mint_bearer_token(secret: str, user_id: str) -> str:
    payload = {
        "sub": user_id,
        "aud": "authenticated",
        "email": f"{user_id}@example.com",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _seed_profile(*, run_id: uuid.UUID, user_id: str) -> UserProfile:
    """A candidate with a real record on file.

    Provenance is deliberately mixed — the contact bundle and links are
    `user_entered`, the work history, education, and skills came off a
    parsed resume — so the finished documents have to trace to more than one
    source, the way a real candidate's would. Nothing here mentions
    `_DECLINED_SKILL` or `_ANSWERABLE_SKILL`: the first is the fabrication
    canary and the second only ever enters the corpus through the gap
    question loop.
    """
    profile = UserProfile(
        id=f"epic04-profile-{run_id}",
        user_id=user_id,
        full_name="Dana Whitfield",
        email=EmailAddress(f"{user_id}@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
        phone="512-555-0148",
        headline="Backend engineer working on logistics data platforms",
        location="Austin, Texas",
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )
    profile.set_address(
        Address(city="Austin", state_or_region="Texas", country="United States"),
        ProvenanceSource.USER_ENTERED,
    )
    profile.set_links(
        ProfileLinks(github_url="https://github.com/danawhitfield"),
        ProvenanceSource.USER_ENTERED,
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"epic04-work-1-{run_id}",
            company_name="Northwind Freight",
            job_title="Senior Backend Engineer",
            start_date=date(2021, 4, 1),
            source=ProvenanceSource.PARSED_RESUME,
            location="Austin, Texas",
            description=(
                "Built Python services for shipment tracking and moved the "
                "billing database onto PostgreSQL"
            ),
        )
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"epic04-work-2-{run_id}",
            company_name="Harborlight Analytics",
            job_title="Backend Engineer",
            start_date=date(2018, 6, 1),
            end_date=date(2021, 3, 1),
            source=ProvenanceSource.PARSED_RESUME,
            description="Maintained reporting APIs in Python and Django",
        )
    )
    profile.add_education(
        EducationEntry(
            id=f"epic04-education-{run_id}",
            institution_name="University of Texas at Austin",
            degree="Bachelor of Science",
            source=ProvenanceSource.PARSED_RESUME,
            field_of_study="Computer Science",
            end_date=date(2018, 5, 1),
        )
    )
    for index, (name, years) in enumerate(
        (("Python", 7), ("PostgreSQL", 6), ("FastAPI", 3), ("Docker", 5)), start=1
    ):
        profile.add_skill(
            Skill(
                id=f"epic04-skill-{index}-{run_id}",
                name=name,
                source=ProvenanceSource.PARSED_RESUME,
                years_of_experience=years,
            )
        )
    return profile


def _seed_posting(*, job_id: str) -> JobPosting:
    """A posting whose requirements the candidate only partly meets.

    `required_skills` names both the answerable and the declined skill, so
    one posting drives both halves of the honesty test.
    """
    posting = JobPosting(
        id=job_id,
        source="acceptance-test",
        company="Cobalt Grid Systems",
        title="Senior Backend Engineer",
        apply_url=f"https://example.com/jobs/{job_id}",
        description=(
            "We are hiring a senior backend engineer to work on our event "
            "processing platform. You will own Python services end to end, "
            f"operate {_DECLINED_SKILL} workloads, and build streaming "
            f"pipelines on {_ANSWERABLE_SKILL}."
        ),
        location="Austin, Texas",
    )
    posting.set_requirements(
        JobRequirements(
            required_skills=("Python", "PostgreSQL", _DECLINED_SKILL),
            preferred_skills=(_ANSWERABLE_SKILL,),
            min_years_experience=5,
        )
    )
    return posting


def _find_gap(gaps: list[str], skill: str) -> str:
    matching = [gap for gap in gaps if skill.lower() in gap.lower()]
    assert matching, (
        f"gap detection did not flag {skill!r}, which nothing in the "
        f"candidate's record backs; gaps were: {gaps}"
    )
    return matching[0]


def _assert_plain_text_is_ats_safe(content: str, *, label: str) -> None:
    """Assert `content` breaks none of the ATS rules that apply to any
    plain-text document.

    The markup/character rules are checked for both documents; the
    heading and section rules are resume-shaped (a cover letter has no
    section headings to recognize or hollow out), so the resume is
    additionally validated in full at its own call site.
    """
    universal_rules = {
        RULE_MARKDOWN_SYNTAX,
        RULE_TABLE_MARKUP,
        RULE_COLUMN_WHITESPACE,
        RULE_DECORATIVE_GLYPH,
        RULE_UNRENDERABLE_CHARACTER,
    }
    found = [
        violation
        for violation in AtsSafetyValidator().validate(content).violations
        if violation.rule in universal_rules
    ]
    assert not found, f"{label} is not ATS-safe plain text: {found}"


@pytest.mark.asyncio
async def test_epic04_definition_of_done(schema_ready: None) -> None:
    get_settings.cache_clear()
    settings = get_settings()

    jwt_secret = settings.supabase_jwt_secret.get_secret_value()
    if not jwt_secret:
        pytest.skip("SUPABASE_JWT_SECRET is not configured; cannot mint a test token")
    if not settings.anthropic_api_key.get_secret_value():
        pytest.skip("ANTHROPIC_API_KEY is not configured")
    if not settings.openai_api_key.get_secret_value():
        pytest.skip(
            "OPENAI_API_KEY is not configured; the gap-resolution loop's answer "
            "memory needs real embeddings"
        )

    # `schema_ready` may run on a different event loop than this test body
    # under pytest-asyncio's fixture/test loop scoping — see the loop-handoff
    # note further down for why this matters.
    await dispose_engine()

    run_id = uuid.uuid4()
    user_id = f"epic04-candidate-{run_id}"
    token = _mint_bearer_token(jwt_secret, user_id)
    auth = {"Authorization": f"Bearer {token}"}
    http_client = TestClient(create_app())

    job_id = f"epic04-job-{run_id}"
    profile = _seed_profile(run_id=run_id, user_id=user_id)
    posting = _seed_posting(job_id=job_id)

    async with async_session_factory() as session:
        await SqlAlchemyProfileRepository(session).add(profile)
        await SqlAlchemyJobPostingRepository(session).add(posting)

    # `TestClient` drives each request's DB access through its own short-lived
    # event loop (a fresh one per call, not shared with this test coroutine's,
    # and not necessarily reused between calls either) — reusing a pooled
    # connection opened on one loop from another raises asyncpg's "attached to
    # a different loop" error. Disposing the shared engine's pool before every
    # DB-touching call forces a fresh connection on the loop that call actually
    # runs on.
    await dispose_engine()

    try:
        # ---- 0. the auth gate is live -------------------------------------
        # First, and on a route that would otherwise spend money: if this
        # ever stops returning 401, the run must fail before it pays for a
        # resume nobody was authorized to ask for.
        unauthenticated = http_client.post(
            f"/api/job-postings/{job_id}/tailored-resume"
        )
        assert unauthenticated.status_code == 401

        # ---- 1. detect the gaps -------------------------------------------
        await dispose_engine()  # see the loop-handoff note above
        gaps_response = http_client.get(
            f"/api/job-postings/{job_id}/gaps", headers=auth
        )
        assert gaps_response.status_code == 200, gaps_response.text
        gaps = gaps_response.json()["gaps"]
        assert gaps_response.json()["job_posting_id"] == job_id
        assert gaps, "the posting asks for skills the record does not back"

        answerable_gap = _find_gap(gaps, _ANSWERABLE_SKILL)
        declined_gap = _find_gap(gaps, _DECLINED_SKILL)

        # ---- 2. the question loop, first pass -----------------------------
        await dispose_engine()  # see the loop-handoff note above
        first_pass = http_client.post(
            "/api/gap-resolution/questions", headers=auth, json={"gaps": gaps}
        )
        assert first_pass.status_code == 200, first_pass.text
        first_pass_body = first_pass.json()
        assert first_pass_body["already_answered"] == [], (
            "a candidate who has answered nothing has nothing to suppress"
        )
        questions = {
            item["gap"]: item["question"] for item in first_pass_body["questions"]
        }
        assert set(questions) == set(gaps), (
            "every detected gap must produce a question, in input order"
        )
        assert [item["gap"] for item in first_pass_body["questions"]] == gaps
        for gap, question in questions.items():
            assert question.strip(), f"empty question generated for gap {gap!r}"

        # ---- 3. answer one gap truthfully, decline the rest ---------------
        await dispose_engine()  # see the loop-handoff note above
        captured = http_client.post(
            "/api/gap-resolution/answers",
            headers=auth,
            json={
                "gap": answerable_gap,
                "question": questions[answerable_gap],
                "answer": _KAFKA_ANSWER,
            },
        )
        assert captured.status_code == 200, captured.text
        captured_body = captured.json()
        assert captured_body["captured"] is True
        answer_memory_id = captured_body["answer_memory_id"]
        assert answer_memory_id

        for gap in (gap for gap in gaps if gap != answerable_gap):
            await dispose_engine()  # see the loop-handoff note above
            declined = http_client.post(
                "/api/gap-resolution/answers",
                headers=auth,
                json={
                    "gap": gap,
                    "question": questions[gap],
                    "answer": _DECLINE,
                },
            )
            assert declined.status_code == 200, declined.text
            declined_body = declined.json()
            assert declined_body["captured"] is False, (
                f"a decline must not be captured as experience: {gap!r}"
            )
            assert declined_body["answer_memory_id"] is None

        # A declined gap leaves NO trace — not an empty answer, not a
        # partial row. The one stored memory is the one real answer.
        await dispose_engine()  # see the loop-handoff note above
        async with async_session_factory() as session:
            stored_memories = await SqlAlchemyAnswerMemoryRepository(
                session
            ).list_by_user_id(user_id)
        assert [memory.id for memory in stored_memories] == [answer_memory_id]
        assert stored_memories[0].source is ProvenanceSource.ANSWER
        assert stored_memories[0].answer_text == _KAFKA_ANSWER

        # ---- 4. the question loop, second pass ----------------------------
        # The answered gap is now suppressed at the production default
        # threshold — the question is generated afresh and its wording will
        # differ, so a match here is semantic, not textual. The declined
        # gaps are still asked: declining is not answering.
        await dispose_engine()  # see the loop-handoff note above
        second_pass = http_client.post(
            "/api/gap-resolution/questions", headers=auth, json={"gaps": gaps}
        )
        assert second_pass.status_code == 200, second_pass.text
        second_pass_body = second_pass.json()
        suppressed = {
            item["gap"]: item for item in second_pass_body["already_answered"]
        }
        assert answerable_gap in suppressed, (
            "the remembered answer must suppress a re-ask of the gap it "
            f"resolved; already_answered was: {second_pass_body['already_answered']}"
        )
        assert suppressed[answerable_gap]["answer_memory_id"] == answer_memory_id
        assert suppressed[answerable_gap]["similarity_score"] >= 0.85
        still_asked = {item["gap"] for item in second_pass_body["questions"]}
        assert declined_gap in still_asked, (
            "a declined gap is unresolved, not answered, and must still be asked"
        )

        # The corpus the generated documents may draw on, assembled the same
        # way the generation flows assemble it — with the captured answer now
        # in it. Everything below is checked against this, independently of
        # the guard run that happened inside the flow.
        await dispose_engine()  # see the loop-handoff note above
        async with async_session_factory() as session:
            facts = await ProvenanceFactAssembler(
                profile_repository=SqlAlchemyProfileRepository(session),
                answer_memory_repository=SqlAlchemyAnswerMemoryRepository(session),
            ).assemble(user_id)
        assert any(fact.source is ProvenanceSource.ANSWER for fact in facts), (
            "the captured answer must be part of what may be asserted"
        )

        def assert_every_line_is_attested(content: str, *, label: str) -> None:
            """Re-validate finished content against the candidate's facts.

            Criterion 2 in one check: re-running the guard over what shipped
            must remove nothing (every line still traces to a
            provenance-backed fact) and must find something attested (the
            document actually says something about the candidate).
            """
            recheck = ProvenanceGuard().enforce(
                content,
                facts=facts,
                context_terms=(posting.title, posting.company, posting.location or ""),
            )
            assert recheck.violations == (), (
                f"{label} contains lines the candidate's facts do not back: "
                f"{recheck.violations}"
            )
            assert recheck.content == content
            assert recheck.has_attested_content

        # ---- 5. the tailored resume ---------------------------------------
        await dispose_engine()  # see the loop-handoff note above
        resume_response = http_client.post(
            f"/api/job-postings/{job_id}/tailored-resume", headers=auth
        )
        assert resume_response.status_code == 201, resume_response.text
        resume_body = resume_response.json()
        resume_document = resume_body["document"]
        resume_content = resume_document["content"]

        assert resume_document["document_kind"] == "tailored_resume"
        assert resume_document["job_posting_id"] == job_id
        assert resume_document["version"] == 1
        assert resume_content.strip()
        assert set(resume_document["backing_sources"]) <= {
            source.value for source in ProvenanceSource
        }
        assert resume_document["backing_sources"], (
            "a resume with no backing provenance is not something to hand over"
        )
        assert_every_line_is_attested(resume_content, label="the tailored resume")

        # The fabrication canary: the posting demands this skill, so the
        # model was under real pressure to claim it, and the candidate
        # declined it. It must appear nowhere.
        assert _DECLINED_SKILL.lower() not in resume_content.lower(), (
            f"the resume claims {_DECLINED_SKILL}, which the candidate declined"
        )
        # Conversely, if it draws on the answered gap, that claim traces to
        # the answer the candidate gave — never to the posting's wish list.
        if _ANSWERABLE_SKILL.lower() in resume_content.lower():
            assert ProvenanceSource.ANSWER.value in resume_document["backing_sources"]

        # ATS safety: the flow's own report, then the same rules re-checked
        # here in full (the resume is the document the heading/section rules
        # are written for).
        assert resume_body["ats_safety_violations"] == [], (
            "the formatter let an ATS-hostile construct through"
        )
        assert AtsSafetyValidator().validate(resume_content).is_safe
        _assert_plain_text_is_ats_safe(resume_content, label="the tailored resume")

        # All three exports are the one guarded text: identical, parseable,
        # rendered.
        exports = resume_body["exports"]
        assert exports["text"] == resume_content
        assert exports["contact_lines"], "an ATS reads the contact block first"
        assert exports["sections"], "an ATS reads the resume as named sections"
        for section in exports["sections"]:
            assert is_standard_section_heading(section["heading"]), (
                f'{section["heading"]!r} is a heading an ATS will file under "other"'
            )
            assert section["lines"], (
                f"section {section['heading']!r} is a heading over nothing"
            )
        pdf_bytes = base64.b64decode(exports["pdf_base64"])
        assert pdf_bytes.startswith(b"%PDF"), "the PDF export is not a PDF file"
        assert exports["pdf_byte_size"] == len(pdf_bytes)

        # ---- 6. the cover letter ------------------------------------------
        await dispose_engine()  # see the loop-handoff note above
        letter_response = http_client.post(
            f"/api/job-postings/{job_id}/cover-letter", headers=auth
        )
        assert letter_response.status_code == 201, letter_response.text
        letter_document = letter_response.json()
        letter_content = letter_document["content"]

        assert letter_document["document_kind"] == "cover_letter"
        assert letter_document["job_posting_id"] == job_id
        assert letter_document["version"] == 1
        assert letter_content.strip()
        assert letter_document["backing_sources"]
        assert_every_line_is_attested(letter_content, label="the cover letter")
        assert _DECLINED_SKILL.lower() not in letter_content.lower(), (
            f"the letter claims {_DECLINED_SKILL}, which the candidate declined"
        )
        if _ANSWERABLE_SKILL.lower() in letter_content.lower():
            assert ProvenanceSource.ANSWER.value in letter_document["backing_sources"]
        _assert_plain_text_is_ats_safe(letter_content, label="the cover letter")

        # ---- 7. the exact sent versions are stored ------------------------
        expected = {
            "tailored_resume": (resume_document, resume_content),
            "cover_letter": (letter_document, letter_content),
        }

        await dispose_engine()  # see the loop-handoff note above
        job_documents = http_client.get(
            f"/api/job-postings/{job_id}/documents", headers=auth
        )
        assert job_documents.status_code == 200, job_documents.text
        summaries = {entry["document_kind"]: entry for entry in job_documents.json()}
        assert set(summaries) == set(expected), (
            f"both documents must be recorded for this job; got {list(summaries)}"
        )

        for kind, (document, content) in expected.items():
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

            summary = summaries[kind]
            assert summary["id"] == document["document_id"]
            assert summary["version"] == 1
            assert summary["content_sha256"] == digest
            assert summary["backing_sources"] == document["backing_sources"]

            # The reuse path the tracker and interview prep read: what this
            # application went out with, not a regeneration of it.
            await dispose_engine()  # see the loop-handoff note above
            latest = http_client.get(
                f"/api/job-postings/{job_id}/documents/{kind}/latest", headers=auth
            )
            assert latest.status_code == 200, latest.text
            latest_body = latest.json()
            assert latest_body["content"] == content, (
                f"the stored {kind} is not the text that was returned"
            )
            assert latest_body["content_sha256"] == digest
            assert latest_body["id"] == document["document_id"]
            assert latest_body["version"] == 1

            # And by id, which is what the tracker feed links to.
            await dispose_engine()  # see the loop-handoff note above
            by_id = http_client.get(
                f"/api/application-documents/{document['document_id']}", headers=auth
            )
            assert by_id.status_code == 200, by_id.text
            assert by_id.json()["content"] == content
            assert by_id.json()["content_sha256"] == digest

        await dispose_engine()  # see the loop-handoff note above
        feed = http_client.get("/api/application-documents", headers=auth)
        assert feed.status_code == 200, feed.text
        assert {entry["id"] for entry in feed.json()} == {
            document["document_id"] for document, _ in expected.values()
        }
    finally:
        # The candidate profile and the one remembered answer are cleaned up.
        # The seeded posting and the two stored snapshots are left in place
        # deliberately: they are the artifact this check exists to prove
        # exists, and neither `JobPostingRepository` nor
        # `ApplicationDocumentRepository` exposes a delete method (a record
        # of what was sent must not be erasable — see `ApplicationDocument`)
        # — the same convention `test_epic03_matching_pipeline.py` follows.
        await dispose_engine()  # see the loop-handoff note above
        async with async_session_factory() as session:
            answer_memory_repository = SqlAlchemyAnswerMemoryRepository(session)
            for memory in await answer_memory_repository.list_by_user_id(user_id):
                await answer_memory_repository.delete(memory.id)
            await SqlAlchemyProfileRepository(session).delete(profile.id)
