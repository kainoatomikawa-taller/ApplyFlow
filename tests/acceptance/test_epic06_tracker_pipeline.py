"""Epic 06 acceptance check — the tracker's Definition of Done.

Runs the ONE flow described in `docs/epic-06-acceptance-check.md` against
REAL infrastructure (a real Postgres database and the real HTTP app with real
Supabase-JWT auth) — no fakes, no mocks, no dependency overrides. Opt-in, like
the other real-infra checks in this suite, so `pytest` never touches a real
database unless a developer deliberately asks for it:

    RUN_EPIC06_ACCEPTANCE_TEST=1 \
      pytest tests/acceptance/test_epic06_tracker_pipeline.py -v -s

Requires, via `.env` or exported env vars:
    DATABASE_URL          a reachable Postgres (local `docker compose up db`
                          or a Supabase project)
    SUPABASE_JWT_SECRET   used both to mint this test's bearer tokens and by
                          the app to verify them, so the run proves the real
                          auth path rather than bypassing it
    ANTHROPIC_API_KEY     needed only by the matched-jobs route, whose
                          rationale generator is constructed eagerly. The
                          suppression check costs at most two cheap-tier
                          calls, because a suppressed posting is dropped
                          *before* any rationale is generated.

No browser, and why that is the right scope
-------------------------------------------
The tracker is fed by submitting, and submitting a review is what Epic 05's
check already proves against a real Chromium and a real portal
(`test_epic05_autofill_pipeline.py`). Re-driving that here would re-prove
someone else's epic and make this check depend on a browser it has nothing to
say about. So this starts from Epic 05's *artifact* — a real
`ApplicationReview` row, seeded through the real repository — and every step
from the submission onward is production code: the real
`POST /api/application-reviews/{id}/submit`, the real `SubmitApplicationReview`,
the real `SubmittedApplicationLog`, the real repositories, and the real tracker
and matching routes. The same convention `test_epic04_tailoring_pipeline.py`
follows when it seeds Epic 03's output instead of re-ranking.

The single flow, in order:
  0. The auth gate first — an unauthenticated read of the tracker is 401.
  1. Seed one candidate, two postings (one they will apply to, one control),
     and the two documents Epic 04 archives for the applied-to posting.
  2. The tracker is empty, and both postings are in the matched list. This is
     the control: whatever changes below is caused by applying.
  3. Submit the review through the real route (criterion 1).
  4. A *newer* resume version is archived for the same job afterwards — the
     sharpest test of "the exact sent documents": the tracker must keep
     naming v1, the one the employer received, not the newest one on file.
  5. The tracker row is checked against what was sent, and the referenced
     snapshot is read back and compared byte for byte (criterion 1).
  6. The status is moved through its lifecycle and the change is re-read from
     the API the UI renders from; illegal moves are refused (criterion 2).
  7. The applied-to role is gone from the matched list, and is still gone
     after the application is rejected (criterion 3).
  8. Submitting again is refused and the tracker still holds exactly one row.
  9. Another candidate sees none of it.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import httpx
import jwt
import pytest

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.application_review import ApplicationReview
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.value_objects.address import Address
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.config import get_settings
from src.infrastructure.persistence.application_document_repository_impl import (
    SqlAlchemyApplicationDocumentRepository,
)
from src.infrastructure.persistence.application_review_repository_impl import (
    SqlAlchemyApplicationReviewRepository,
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
    os.getenv("RUN_EPIC06_ACCEPTANCE_TEST") != "1",
    reason=(
        "opt-in: set RUN_EPIC06_ACCEPTANCE_TEST=1 with DATABASE_URL, "
        "SUPABASE_JWT_SECRET, and ANTHROPIC_API_KEY configured to run the "
        "Epic 06 Definition-of-Done check (see "
        "docs/epic-06-acceptance-check.md)"
    ),
)

#: The resume that goes out with the application. Its exact text is what the
#: tracker has to keep pointing at, so it says so.
_SENT_RESUME = (
    "DANA WHITFIELD\n"
    "Austin, Texas\n"
    "\n"
    "EXPERIENCE\n"
    "Senior Backend Engineer, Northwind Freight (2021-present)\n"
    "Built Python services for shipment tracking on PostgreSQL.\n"
    "\n"
    "SKILLS\n"
    "Python, PostgreSQL, FastAPI, Docker\n"
)

_SENT_COVER_LETTER = (
    "Dear Globex team,\n"
    "\n"
    "I have run shipment-tracking services in production for four years and "
    "would like to bring that to your platform group.\n"
    "\n"
    "Dana Whitfield\n"
)

#: Archived *after* the submission. Never sent to anyone; it exists purely so
#: the tracker can be caught showing the newest document instead of the one
#: that went out.
_LATER_RESUME_REVISION = _SENT_RESUME + "\nOPEN SOURCE\nMaintainer, freight-tools\n"


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
    """A candidate who qualifies for both seeded postings.

    Kept deliberately plain: this check is about what happens to an
    application after it is sent, so nothing here should be able to disqualify
    the candidate and make a posting vanish from the matched list for a reason
    other than the one under test.
    """
    profile = UserProfile(
        id=f"epic06-profile-{run_id}",
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
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"epic06-work-{run_id}",
            company_name="Northwind Freight",
            job_title="Senior Backend Engineer",
            start_date=date(2021, 4, 1),
            source=ProvenanceSource.PARSED_RESUME,
            location="Austin, Texas",
            description="Built Python services for shipment tracking.",
        )
    )
    for index, (name, years) in enumerate(
        (("Python", 7), ("PostgreSQL", 6), ("FastAPI", 3)), start=1
    ):
        profile.add_skill(
            Skill(
                id=f"epic06-skill-{index}-{run_id}",
                name=name,
                source=ProvenanceSource.PARSED_RESUME,
                years_of_experience=years,
            )
        )
    return profile


def _seed_posting(
    *, job_id: str, company: str, title: str, location: str
) -> JobPosting:
    """A posting the candidate qualifies for.

    `requirements` asks only for things the seeded profile has, so the
    hard-disqualifier filter keeps both postings in the matched list until
    suppression is what removes one.
    """
    return JobPosting(
        id=job_id,
        source="greenhouse",
        company=company,
        title=title,
        apply_url=f"https://boards.greenhouse.io/{company.lower()}/jobs/{job_id}",
        description=f"{title} at {company}.",
        location=location,
        requirements=JobRequirements(
            required_skills=("Python",),
            preferred_skills=("PostgreSQL",),
        ),
    )


def _document(
    *,
    document_id: str,
    user_id: str,
    job_posting_id: str,
    kind: GeneratedDocumentKind,
    content: str,
    version: int,
) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


def _seed_review(
    *, review_id: str, user_id: str, posting: JobPosting
) -> ApplicationReview:
    """Epic 05's artifact: a filled application waiting on the candidate.

    Every answer is settled — autofilled from the record, and none of them
    sensitive — so nothing blocks submission. A review with an undecided legal
    declaration is Epic 05's subject, and refusing to submit it is proven
    there; what this check needs is a submission that goes through, so the
    tracker has something to record.
    """
    return ApplicationReview.open_for(
        review_id=review_id,
        user_id=user_id,
        job_posting_id=posting.id,
        apply_url=posting.apply_url,
        ats_provider="greenhouse",
        answers=(
            ReviewedAnswer(
                key="job_application[first_name]",
                label="First Name",
                widget_kind="text",
                value="Dana",
                required=True,
                origin=AnswerOrigin.AUTOFILLED,
            ),
            ReviewedAnswer(
                key="job_application[last_name]",
                label="Last Name",
                widget_kind="text",
                value="Whitfield",
                required=True,
                origin=AnswerOrigin.AUTOFILLED,
            ),
            ReviewedAnswer(
                key="job_application[email]",
                label="Email",
                widget_kind="email",
                value=f"{user_id}@example.com",
                required=True,
                origin=AnswerOrigin.AUTOFILLED,
            ),
        ),
        screenshot_captured=True,
    )


async def test_epic06_definition_of_done(schema_ready: None) -> None:
    get_settings.cache_clear()
    settings = get_settings()

    jwt_secret = settings.supabase_jwt_secret.get_secret_value()
    if not jwt_secret:
        pytest.skip("SUPABASE_JWT_SECRET is not configured; cannot mint a test token")
    if not settings.anthropic_api_key.get_secret_value():
        pytest.skip(
            "ANTHROPIC_API_KEY is not configured; the matched-jobs route builds "
            "its rationale generator eagerly, so criterion 3 cannot be checked "
            "without it"
        )

    # `schema_ready` may run on a different event loop than this test body
    # under pytest-asyncio's fixture/test loop scoping — see the loop-handoff
    # note further down for why this matters.
    await dispose_engine()

    run_id = uuid.uuid4()
    user_id = f"epic06-candidate-{run_id}"
    other_user_id = f"epic06-bystander-{run_id}"
    auth = {"Authorization": f"Bearer {_mint_bearer_token(jwt_secret, user_id)}"}
    other_auth = {
        "Authorization": f"Bearer {_mint_bearer_token(jwt_secret, other_user_id)}"
    }
    # An ASGI transport rather than `TestClient`: every request runs on
    # *this* test's event loop, so a pooled asyncpg connection opened during
    # one request is still usable during the next. `TestClient` drives each
    # call through its own short-lived loop, which turns every second
    # DB-touching request into asyncpg's "attached to a different loop".
    # A real server runs one loop too, so this is also the truer shape.
    transport = httpx.ASGITransport(app=create_app())
    http_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    applied_job_id = f"epic06-job-applied-{run_id}"
    control_job_id = f"epic06-job-control-{run_id}"
    review_id = f"epic06-review-{run_id}"

    profile = _seed_profile(run_id=run_id, user_id=user_id)
    applied_posting = _seed_posting(
        job_id=applied_job_id,
        company="Globex",
        title="Senior Platform Engineer",
        location="Austin, Texas",
    )
    control_posting = _seed_posting(
        job_id=control_job_id,
        company="Initech",
        title="Staff Backend Engineer",
        location="Austin, Texas",
    )
    sent_resume = _document(
        document_id=f"epic06-resume-v1-{run_id}",
        user_id=user_id,
        job_posting_id=applied_job_id,
        kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=_SENT_RESUME,
        version=1,
    )
    sent_cover_letter = _document(
        document_id=f"epic06-letter-v1-{run_id}",
        user_id=user_id,
        job_posting_id=applied_job_id,
        kind=GeneratedDocumentKind.COVER_LETTER,
        content=_SENT_COVER_LETTER,
        version=1,
    )
    review = _seed_review(review_id=review_id, user_id=user_id, posting=applied_posting)

    async with async_session_factory() as session:
        await SqlAlchemyProfileRepository(session).add(profile)
        posting_repository = SqlAlchemyJobPostingRepository(session)
        await posting_repository.add(applied_posting)
        await posting_repository.add(control_posting)
        document_repository = SqlAlchemyApplicationDocumentRepository(session)
        await document_repository.add(sent_resume)
        await document_repository.add(sent_cover_letter)
        await SqlAlchemyApplicationReviewRepository(session).add(review)

    try:
        # -- 0. The auth gate, before anything else --------------------------
        #
        # First deliberately: a tracker is a record of where someone is
        # applying for work, and if the gate ever stops holding, this run
        # fails before a single row of it is read.
        unauthenticated = await http_client.get("/api/tracked-applications")
        assert unauthenticated.status_code == 401
        unauthenticated_write = await http_client.patch(
            "/api/tracked-applications/anything/status",
            json={"status": "interviewing"},
        )
        assert unauthenticated_write.status_code == 401

        # -- 1. The control: nothing sent, nothing suppressed ----------------
        empty = await http_client.get("/api/tracked-applications", headers=auth)
        assert empty.status_code == 200, empty.text
        assert empty.json()["applications"] == []
        assert empty.json()["open_count"] == 0

        before = await http_client.get("/api/job-postings/matches", headers=auth)
        assert before.status_code == 200, before.text
        matched_before = {entry["job_posting"]["id"] for entry in before.json()}
        assert applied_job_id in matched_before
        assert control_job_id in matched_before, (
            "the control posting must be matchable, or its absence later "
            "proves nothing"
        )

        # -- 2. The candidate submits (criterion 1) --------------------------
        submitted = await http_client.post(
            f"/api/application-reviews/{review_id}/submit",
            json={"note": "Sent from my own browser."},
            headers=auth,
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["review"]["status"] == "submitted_by_user"
        submitted_at = submitted.json()["review"]["submitted_at"]
        assert submitted_at is not None

        # -- 3. A newer resume is archived afterwards ------------------------
        #
        # The candidate revises their resume for this same job the next day.
        # Nothing sent it anywhere; it is here so that "the tracker shows the
        # newest document" would be caught, because that is the failure the
        # whole snapshot-by-id design exists to prevent.
        later_revision = _document(
            document_id=f"epic06-resume-v2-{run_id}",
            user_id=user_id,
            job_posting_id=applied_job_id,
            kind=GeneratedDocumentKind.TAILORED_RESUME,
            content=_LATER_RESUME_REVISION,
            version=2,
        )
        async with async_session_factory() as session:
            await SqlAlchemyApplicationDocumentRepository(session).add(later_revision)

        # -- 4. The tracker logged it, with the documents that went out ------
        feed = await http_client.get("/api/tracked-applications", headers=auth)
        assert feed.status_code == 200, feed.text
        rows = feed.json()["applications"]
        assert len(rows) == 1, "one submission, one tracked application"
        (row,) = rows

        application_id = row["id"]
        assert row["job_posting_id"] == applied_job_id
        # Copied off the posting at record time, not joined at read time.
        assert row["company_name"] == "Globex"
        assert row["role_title"] == "Senior Platform Engineer"
        assert row["job_location"] == "Austin, Texas"
        assert row["status"] == "applied"
        assert row["is_open"] is True
        # The date is the submission's own, not the moment the tracker was read.
        assert row["applied_at"][:19] == submitted_at[:19]

        # The exact documents: the resume that was sent, NOT the newer one
        # archived a moment ago.
        assert row["resume"]["id"] == sent_resume.id
        assert row["resume"]["version"] == 1
        assert row["resume"]["content_sha256"] == sent_resume.content_sha256
        assert row["resume"]["id"] != later_revision.id
        assert row["cover_letter"]["id"] == sent_cover_letter.id
        assert row["cover_letter"]["document_kind"] == "cover_letter"
        # The feed identifies documents; it never carries their text.
        assert "content" not in row["resume"]

        # A sent application starts with a one-entry history: it was applied
        # to, and nothing has happened since. `previous_status` is null for
        # exactly that first entry.
        assert [entry["status"] for entry in row["status_history"]] == ["applied"]
        assert row["status_history"][0]["previous_status"] is None
        assert row["current_status_since"][:19] == submitted_at[:19]

        # And the reference resolves to the bytes that were archived — the
        # claim "these are the exact sent documents", followed all the way
        # through rather than asserted about an id.
        for reference, expected in (
            (row["resume"], _SENT_RESUME),
            (row["cover_letter"], _SENT_COVER_LETTER),
        ):
            stored = await http_client.get(
                f"/api/application-documents/{reference['id']}", headers=auth
            )
            assert stored.status_code == 200, stored.text
            assert stored.json()["content"] == expected
            assert stored.json()["content_sha256"] == reference["content_sha256"]

        # -- 5. The status is maintainable (criterion 2) ---------------------
        #
        # The choices offered come from the domain's state machine, so a client
        # can only ever propose a move the route will accept.
        assert row["allowed_next_statuses"] == [
            "interviewing",
            "rejected",
            "withdrawn",
        ]

        moved = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "interviewing", "note": "recruiter reached out"},
            headers=auth,
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == "interviewing"
        # The next set of choices came back with it, so the control that made
        # the change re-renders from what was stored.
        assert moved.json()["allowed_next_statuses"] == [
            "offer",
            "rejected",
            "withdrawn",
        ]
        # The move was recorded, not just applied: the history grew by one
        # entry that names where it came from and carries the candidate's own
        # note, and `current_status_since` moved off the submission date.
        history = moved.json()["status_history"]
        assert [entry["status"] for entry in history] == ["applied", "interviewing"]
        assert history[-1]["previous_status"] == "applied"
        assert history[-1]["note"] == "recruiter reached out"
        assert moved.json()["current_status_since"] > moved.json()["applied_at"]

        # It reflects in what the UI reads — the same route the tracker screen
        # renders from, not the response of the write.
        reread = (
            await http_client.get("/api/tracked-applications", headers=auth)
        ).json()["applications"]
        assert reread[0]["status"] == "interviewing"
        # And the change did not disturb what was sent.
        assert reread[0]["resume"]["id"] == sent_resume.id

        # A value that is not a status at all: refused as unprocessable.
        nonsense = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "ghosted"},
            headers=auth,
        )
        assert nonsense.status_code == 422

        # A real status the lifecycle does not allow from here: refused as a
        # conflict, and nothing is written.
        backwards = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "applied"},
            headers=auth,
        )
        assert backwards.status_code == 409
        unchanged = (
            await http_client.get("/api/tracked-applications", headers=auth)
        ).json()["applications"]
        assert unchanged[0]["status"] == "interviewing"

        # A sent application can never become a draft again. A 422 rather than
        # a 409: `draft` is a real status, but not one this record can ever
        # hold, so the answer is "that is not a value for this field" and the
        # message names what to do instead (open an ApplicationReview).
        undo = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "draft"},
            headers=auth,
        )
        assert undo.status_code == 422
        assert "ApplicationReview" in undo.json()["detail"]

        # Through to a terminal status, which offers nothing further.
        rejected = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "rejected"},
            headers=auth,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["is_open"] is False
        assert rejected.json()["allowed_next_statuses"] == []
        # Every step the application took is still on the record. A tracker
        # that only kept the current status could not answer "how long was I
        # in play before they passed?".
        assert [entry["status"] for entry in rejected.json()["status_history"]] == [
            "applied",
            "interviewing",
            "rejected",
        ]

        # -- 6. The role is not nudged for re-application (criterion 3) ------
        after = await http_client.get("/api/job-postings/matches", headers=auth)
        assert after.status_code == 200, after.text
        matched_after = {entry["job_posting"]["id"] for entry in after.json()}
        assert applied_job_id not in matched_after, (
            "the candidate already applied to this role; the matched list is a "
            "list of jobs to apply to"
        )
        # ...and the control is untouched, so suppression removed one specific
        # role rather than emptying the list.
        assert control_job_id in matched_after

        # Suppressed *after a rejection*, too. A rejection is the strongest
        # possible reason not to suggest applying again, and the index
        # deliberately does not consult status.
        assert rejected.json()["status"] == "rejected"

        # A client that wants a "you already applied" section asks for it, and
        # gets the entry flagged rather than silently mixed back in.
        included = await http_client.get(
            "/api/job-postings/matches?include_already_applied=true", headers=auth
        )
        assert included.status_code == 200, included.text
        by_id = {entry["job_posting"]["id"]: entry for entry in included.json()}
        assert by_id[applied_job_id]["already_applied"] is True
        assert by_id[control_job_id]["already_applied"] is False

        # -- 7. Submitting again is refused, and nothing is double-counted ---
        again = await http_client.post(
            f"/api/application-reviews/{review_id}/submit",
            json={"note": "double-clicked"},
            headers=auth,
        )
        assert again.status_code == 409, again.text
        still_one = (
            await http_client.get("/api/tracked-applications", headers=auth)
        ).json()["applications"]
        assert len(still_one) == 1
        # The replay moved neither the recorded date nor the status the
        # candidate has since set.
        assert still_one[0]["applied_at"][:19] == submitted_at[:19]
        assert still_one[0]["status"] == "rejected"

        # -- 8. Another candidate sees none of it ----------------------------
        theirs = await http_client.get("/api/tracked-applications", headers=other_auth)
        assert theirs.status_code == 200, theirs.text
        assert theirs.json()["applications"] == []
        # And cannot move someone else's application. A 404, not a 403: the
        # API must not confirm that an id it was handed is real.
        not_theirs = await http_client.patch(
            f"/api/tracked-applications/{application_id}/status",
            json={"status": "offer"},
            headers=other_auth,
        )
        assert not_theirs.status_code == 404
    finally:
        # The candidate profile is cleaned up. The seeded postings, the two
        # document snapshots, the review, and the tracked application are left
        # in place deliberately: they are the artifact this check exists to
        # prove exists, and none of those repositories exposes a delete (a
        # record of what was sent must not be erasable — see
        # `ApplicationDocument` and `TrackedApplicationRepository`). The same
        # convention `test_epic04_tailoring_pipeline.py` follows.
        await http_client.aclose()
        async with async_session_factory() as session:
            await SqlAlchemyProfileRepository(session).delete(profile.id)
