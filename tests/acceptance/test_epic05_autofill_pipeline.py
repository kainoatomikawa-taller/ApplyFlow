"""Epic 05 acceptance check — the autofill-and-submit flow's Definition of Done.

Runs the ONE flow described in `docs/epic-05-acceptance-check.md` against
REAL infrastructure: a real Postgres database, the real HTTP app with real
Supabase-JWT auth, a real headless Chromium driving real HTML through
Playwright, and a real HTTP server on the other end that records exactly what
was submitted to it. No fakes, no mocks, no dependency overrides.

    RUN_EPIC05_ACCEPTANCE_TEST=1 \
        pytest tests/acceptance/test_epic05_autofill_pipeline.py -v -s

Requires, via `.env` or exported env vars:
    DATABASE_URL          a reachable Postgres (local `docker compose up db`
                           or a Supabase project)
    SUPABASE_JWT_SECRET    used both to mint this test's bearer token and by
                           the app to verify it, so the run proves the real
                           auth path rather than bypassing it
plus the Chromium build Playwright expects (`playwright install chromium`).
No LLM keys and no money: this epic reads and fills forms, it does not
generate anything — the two documents it attaches are seeded snapshots.

Why the portal is local, and why it is still "a supported ATS"
-------------------------------------------------------------
The one thing this check must not do is submit an application to a real
employer. So the four forms below are served by a local HTTP server bound to
127.0.0.1 — and Chromium is launched with
`--host-resolver-rules=MAP boards.greenhouse.io 127.0.0.1:<port>`, so the
browser really does navigate `http://boards.greenhouse.io/globex/jobs/...`,
`identify_ats_board` really does resolve it to Greenhouse, and the Greenhouse
field-mapping rules really are the ones under test. Nothing about the flow is
stubbed; only the DNS answer is.

The forms are Greenhouse-shaped in the way that matters: the control names
(`job_application[first_name]`, `job_application[resume]`) are what those
rules key on, and the questions include the ones every real form asks —
work authorization, sponsorship, EEO self-identification — plus a screening
question the company wrote itself.

The flow, in order:
  0. An unauthenticated autofill is refused (401), before a browser opens.
  1. `POST /api/job-postings/{id}/autofill` on the good form — the standard
     fields are filled from the profile, the seeded resume is uploaded as a
     PDF, the cover letter is pasted, the work-authorization answer is filled
     and flagged for confirmation, and the two EEO questions and the
     company's screening question are surfaced untouched.
  2. Submitting is refused three times over, and each refusal names what the
     candidate has to do: the legal answer is unconfirmed, then the required
     screening question is unanswered. Nothing reaches the portal.
  3. The candidate answers the screening question and — separately, and only
     because they chose to — one of the two EEO questions.
  4. `POST /api/autofill-sessions/{id}/submit` with the confirmation — the
     application goes out, and the portal's record of it is checked field by
     field: every value ApplyFlow wrote, the uploaded PDF, the candidate's own
     answers, and an EEO field that is *empty* even though the profile has an
     answer on file for it.
  5. The three hard boundaries, each on its own form: a login wall (nothing
     is filled at all), a CAPTCHA, and a signature request. Each hands off
     with an instruction, each refuses submission, and the portal receives
     nothing from any of them.

Everything is asserted twice where it matters: once through the API's own
report, and once against what the portal actually received. A report can be
wrong; a POST body is what was sent.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from email.parser import BytesParser
from email.policy import default as default_policy
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.value_objects.address import Address
from src.domain.value_objects.eeo_categories import GenderIdentity, VeteranStatus
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus
from src.infrastructure.config import get_settings
from src.infrastructure.persistence.application_document_repository_impl import (
    SqlAlchemyApplicationDocumentRepository,
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
from src.interfaces.http.dependencies import (
    get_browser_automation,
    get_review_sessions,
    shutdown_portal_automation,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EPIC05_ACCEPTANCE_TEST") != "1",
    reason=(
        "opt-in: set RUN_EPIC05_ACCEPTANCE_TEST=1 with DATABASE_URL and "
        "SUPABASE_JWT_SECRET configured, and Chromium installed "
        "(`playwright install chromium`), to run the Epic 05 "
        "Definition-of-Done check (see docs/epic-05-acceptance-check.md)"
    ),
)

#: The host the browser is made to resolve to the local server. It has to be
#: one `identify_ats_board` allowlists, or the pass is refused before a
#: browser opens — which is the behavior being relied on, not worked around.
PORTAL_HOST = "boards.greenhouse.io"

#: The candidate's stored resume and cover letter for this job. Seeded as
#: `ApplicationDocument` snapshots, because this epic attaches what Epic 04
#: produced rather than producing anything itself.
RESUME_TEXT = """DANA WHITFIELD
dana@example.com | 512-555-0148 | Austin, Texas

EXPERIENCE
Senior Backend Engineer, Northwind Freight, 2021-04-01 to present
- Built Python services for shipment tracking

SKILLS
- Python (7 years)
- PostgreSQL (6 years)
"""

COVER_LETTER_TEXT = (
    "Dear Cobalt Grid Systems team,\n\n"
    "I am applying for the Senior Backend Engineer role. I have built Python "
    "services for shipment tracking at Northwind Freight since 2021.\n\n"
    "Dana Whitfield\n"
)

#: The company's own screening question — required, and nothing ApplyFlow can
#: answer. The candidate answers it in step 3.
SCREENING_ANSWER = (
    "I have run event-processing services in production for six years and "
    "want to do it at a company where logistics data is the product."
)

#: The candidate's own EEO answer, given on this application only. The
#: profile's stored answer is never what reaches a form.
GENDER_ANSWER = "Female"


# --- the portal's forms ------------------------------------------------------

APPLICATION_FORM_HTML = """<!doctype html>
<html><body>
<h1>Senior Backend Engineer at Globex</h1>
<form action="/globex/jobs/4001/submit" method="post"
      enctype="multipart/form-data">
  <label for="fn">First Name *</label>
  <input id="fn" name="job_application[first_name]" type="text" required>

  <label for="ln">Last Name *</label>
  <input id="ln" name="job_application[last_name]" type="text" required>

  <label for="em">Email *</label>
  <input id="em" name="job_application[email]" type="email" required>

  <label for="ph">Phone</label>
  <input id="ph" name="job_application[phone]" type="tel">

  <label for="loc">Location (City)</label>
  <input id="loc" name="job_application[location]" type="text">

  <label for="li">LinkedIn Profile</label>
  <input id="li" name="job_application[urls][LinkedIn]" type="url">

  <label for="res">Resume/CV *</label>
  <input id="res" name="job_application[resume]" type="file" required>

  <label for="cl">Cover Letter</label>
  <textarea id="cl" name="job_application[cover_letter_text]"></textarea>

  <label for="why">Why do you want to work at Globex? *</label>
  <textarea id="why" name="job_application[answers][why]" required></textarea>

  <label for="auth">Are you legally authorized to work in the United States? *</label>
  <select id="auth" name="job_application[answers][work_authorization]" required>
    <option value="">Please select</option>
    <option value="Yes">Yes</option>
    <option value="No">No</option>
  </select>

  <label for="spon">Will you now or in the future require visa sponsorship? *</label>
  <select id="spon" name="job_application[answers][sponsorship]" required>
    <option value="">Please select</option>
    <option value="Yes">Yes</option>
    <option value="No">No</option>
  </select>

  <fieldset>
    <legend>Voluntary self-identification</legend>
    <label for="gender">Gender</label>
    <select id="gender" name="job_application[eeo][gender]">
      <option value="">Please select</option>
      <option value="Female">Female</option>
      <option value="Male">Male</option>
      <option value="Decline to self-identify">Decline to self-identify</option>
    </select>

    <label for="vet">Veteran status</label>
    <select id="vet" name="job_application[eeo][veteran_status]">
      <option value="">Please select</option>
      <option value="I am not a protected veteran">I am not a protected veteran</option>
      <option value="I am a protected veteran">I am a protected veteran</option>
      <option value="Decline to self-identify">Decline to self-identify</option>
    </select>
  </fieldset>

  <button type="submit">Submit application</button>
</form>
</body></html>
"""

#: A sign-in wall where the application form should be. Nothing on this page
#: may be filled: the email box belongs to an account, not an application.
LOGIN_WALL_HTML = """<!doctype html>
<html><body>
<h1>Please sign in to continue to the application</h1>
<form action="/globex/jobs/4002/session" method="post">
  <label for="em">Email</label>
  <input id="em" name="job_application[email]" type="email">
  <label for="pw">Password</label>
  <input id="pw" name="password" type="password">
  <button type="submit">Sign in</button>
</form>
</body></html>
"""

#: An ordinary form with a challenge widget on it — fillable, not sendable.
CAPTCHA_FORM_HTML = """<!doctype html>
<html><body>
<h1>Senior Backend Engineer at Globex</h1>
<form action="/globex/jobs/4003/submit" method="post">
  <label for="fn">First Name *</label>
  <input id="fn" name="job_application[first_name]" type="text" required>
  <label for="em">Email *</label>
  <input id="em" name="job_application[email]" type="email" required>
  <div class="g-recaptcha" data-sitekey="test-key"></div>
  <iframe title="reCAPTCHA" width="300" height="80"
          src="/recaptcha/api2/anchor"></iframe>
  <button type="submit">Submit application</button>
</form>
</body></html>
"""

#: A form that wants the candidate's signature, in the shape ATS forms
#: actually use: a text input whose label names their own full name.
SIGNATURE_FORM_HTML = """<!doctype html>
<html><body>
<h1>Senior Backend Engineer at Globex</h1>
<form action="/globex/jobs/4004/submit" method="post">
  <label for="fn">First Name *</label>
  <input id="fn" name="job_application[first_name]" type="text" required>
  <label for="em">Email *</label>
  <input id="em" name="job_application[email]" type="email" required>
  <label for="sig">Signature (type your full name) *</label>
  <input id="sig" name="job_application[signature]" type="text" required>
  <button type="submit">Submit application</button>
</form>
</body></html>
"""

CHALLENGE_FRAME_HTML = """<!doctype html>
<html><body><p>I'm not a robot</p></body></html>
"""

THANKS_HTML = """<!doctype html>
<html><body>
<h1>Thanks — your application has been received.</h1>
<p>Globex will be in touch about the Senior Backend Engineer role.</p>
</body></html>
"""


# --- the portal ---------------------------------------------------------------


@dataclass
class Submission:
    """One request the portal received on a submit route."""

    path: str
    #: Text form values, by control name.
    values: dict[str, str] = field(default_factory=dict)
    #: Uploaded files, by control name: (filename, bytes).
    files: dict[str, tuple[str, bytes]] = field(default_factory=dict)


class PortalServer:
    """A local HTTP/1.1 server that serves the four forms and, crucially,
    *records what is posted to it*.

    The recording is the point. Every assertion about what ApplyFlow put on
    the form can be made twice — once against the API's report, and once
    against the bytes the portal received — and only the second one proves
    the report was true. It is also how "nothing is submitted unattended" is
    checked: for three of the four forms, `submissions` must stay empty.
    """

    def __init__(self) -> None:
        self._pages: dict[str, str] = {}
        self.submissions: list[Submission] = []
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    def page(self, path: str, html: str) -> None:
        self._pages[path] = html

    def url(self, path: str) -> str:
        """The URL as the *browser* will see it — the mapped portal host, not
        127.0.0.1, so the apply URL resolves to a supported ATS board."""
        return f"http://{PORTAL_HOST}{path}"

    def submissions_to(self, path: str) -> list[Submission]:
        return [item for item in self.submissions if item.path == path]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode("latin-1").split()
            method = parts[0] if parts else "GET"
            path = parts[1].split("?")[0] if len(parts) > 1 else "/"

            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                name, _, value = line.decode("latin-1").partition(":")
                headers[name.strip().lower()] = value.strip()

            body = b""
            length = int(headers.get("content-length", "0") or 0)
            if length:
                body = await reader.readexactly(length)

            if method == "POST":
                self.submissions.append(
                    _parse_submission(
                        path, headers.get("content-type", ""), body
                    )
                )
                status, page = 303, THANKS_HTML
                head = (
                    "HTTP/1.1 303 See Other\r\n"
                    "Location: /globex/thanks\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                )
                writer.write(head.encode("latin-1"))
                await writer.drain()
                return

            page = self._pages.get(path)
            status = 200 if page is not None else 404
            payload = (page or "<h1>Not found</h1>").encode("utf-8")
            head = (
                f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(head.encode("latin-1") + payload)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass  # the browser gave up on this request
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


def _parse_submission(path: str, content_type: str, body: bytes) -> Submission:
    """Read a form POST into values and files.

    Multipart is parsed with the stdlib email parser rather than by hand:
    the resume arrives as a real multipart upload, and the point of
    recording it is to check the actual bytes the portal received.
    """
    if "multipart/form-data" not in content_type:
        decoded = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        return Submission(
            path=path,
            values={name: values[0] for name, values in decoded.items()},
        )

    message = BytesParser(policy=default_policy).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    )
    submission = Submission(path=path)
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename:
            submission.files[name] = (filename, payload)
        else:
            submission.values[name] = payload.decode("utf-8")
    return submission


# --- seeding ------------------------------------------------------------------


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
    """A candidate whose record answers the legal questions and whose EEO
    answers are on file — the second of which must never reach a form.

    The work authorization is `USER_ENTERED`, which is what makes it
    answerable at all (`WorkAuthorization.ATTESTING_SOURCES` refuses a status
    inferred from a parsed resume). `requires_sponsorship=False` is stated
    explicitly, so the sponsorship question is answered from the candidate's
    own answer rather than derived.
    """
    profile = UserProfile(
        id=f"epic05-profile-{run_id}",
        user_id=user_id,
        full_name="Dana Whitfield",
        email=EmailAddress(f"{user_id}@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
        phone="512-555-0148",
        location="Austin, Texas",
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            citizenship_country="United States",
            requires_sponsorship=False,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )
    profile.set_address(
        Address(city="Austin", state_or_region="Texas", country="United States"),
        ProvenanceSource.USER_ENTERED,
    )
    profile.set_links(
        ProfileLinks(linkedin_url="https://www.linkedin.com/in/danawhitfield"),
        ProvenanceSource.USER_ENTERED,
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"epic05-work-{run_id}",
            company_name="Northwind Freight",
            job_title="Senior Backend Engineer",
            start_date=date(2021, 4, 1),
            source=ProvenanceSource.PARSED_RESUME,
            description="Built Python services for shipment tracking",
        )
    )
    profile.add_skill(
        Skill(
            id=f"epic05-skill-{run_id}",
            name="Python",
            source=ProvenanceSource.PARSED_RESUME,
            years_of_experience=7,
        )
    )
    # On file, complete, and irrelevant to what gets filled: EEO is the
    # candidate's decision per application, so this record exists here only
    # to prove that having it changes nothing.
    profile.set_eeo_self_identification(
        EeoSelfIdentification(
            source=ProvenanceSource.ANSWER,
            gender_identity=GenderIdentity.FEMALE,
            veteran_status=VeteranStatus.NOT_A_PROTECTED_VETERAN,
        )
    )
    return profile


def _seed_posting(*, job_id: str, apply_url: str) -> JobPosting:
    return JobPosting(
        id=job_id,
        source="acceptance-test",
        company="Globex",
        title="Senior Backend Engineer",
        apply_url=apply_url,
        description="Own our event processing services end to end.",
        location="Austin, Texas",
    )


def _seed_documents(*, run_id: uuid.UUID, user_id: str, job_id: str) -> list[
    ApplicationDocument
]:
    return [
        ApplicationDocument(
            id=f"epic05-resume-{run_id}",
            user_id=user_id,
            job_posting_id=job_id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
            content=RESUME_TEXT,
            version=1,
            backing_sources=(ProvenanceSource.PARSED_RESUME,),
        ),
        ApplicationDocument(
            id=f"epic05-letter-{run_id}",
            user_id=user_id,
            job_posting_id=job_id,
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content=COVER_LETTER_TEXT,
            version=1,
            backing_sources=(ProvenanceSource.PARSED_RESUME,),
        ),
    ]


def _field(report: dict[str, Any], label: str) -> dict[str, Any]:
    matching = [item for item in report["fields"] if item["label"] == label]
    assert matching, (
        f"no field labelled {label!r} in the report; the form presented: "
        f"{[item['label'] for item in report['fields']]}"
    )
    return matching[0]


# --- the check ----------------------------------------------------------------


async def test_epic05_definition_of_done(schema_ready: None) -> None:
    portal = PortalServer()
    await portal.start()

    # Chromium resolves the portal host to the local server. The apply URLs
    # stay real Greenhouse board URLs, so `identify_ats_board` accepts them
    # and the Greenhouse mapping rules are the ones exercised.
    previous_launch_args = os.environ.get("BROWSER_LAUNCH_ARGS")
    os.environ["BROWSER_LAUNCH_ARGS"] = json.dumps(
        [f"--host-resolver-rules=MAP {PORTAL_HOST} 127.0.0.1:{portal.port}"]
    )
    get_settings.cache_clear()
    # The browser and the parked-review registry are process-wide singletons;
    # they are rebuilt here so this run gets the launch args above.
    get_browser_automation.cache_clear()
    get_review_sessions.cache_clear()

    settings = get_settings()
    jwt_secret = settings.supabase_jwt_secret.get_secret_value()
    if not jwt_secret:
        await portal.stop()
        pytest.skip("SUPABASE_JWT_SECRET is not configured; cannot mint a test token")

    portal.page("/globex/jobs/4001", APPLICATION_FORM_HTML)
    portal.page("/globex/jobs/4002", LOGIN_WALL_HTML)
    portal.page("/globex/jobs/4003", CAPTCHA_FORM_HTML)
    portal.page("/globex/jobs/4004", SIGNATURE_FORM_HTML)
    portal.page("/recaptcha/api2/anchor", CHALLENGE_FRAME_HTML)
    portal.page("/globex/thanks", THANKS_HTML)

    run_id = uuid.uuid4()
    user_id = f"epic05-candidate-{run_id}"
    auth = {"Authorization": f"Bearer {_mint_bearer_token(jwt_secret, user_id)}"}

    good_job = f"epic05-job-good-{run_id}"
    login_job = f"epic05-job-login-{run_id}"
    captcha_job = f"epic05-job-captcha-{run_id}"
    signature_job = f"epic05-job-signature-{run_id}"

    profile = _seed_profile(run_id=run_id, user_id=user_id)

    # The fixture above may have run on a different event loop than this test
    # body (pytest-asyncio fixture/test loop scoping); a pooled connection
    # opened on one loop cannot be reused from another.
    await dispose_engine()
    async with async_session_factory() as session:
        await SqlAlchemyProfileRepository(session).add(profile)
        posting_repository = SqlAlchemyJobPostingRepository(session)
        document_repository = SqlAlchemyApplicationDocumentRepository(session)
        for job_id, path in (
            (good_job, "/globex/jobs/4001"),
            (login_job, "/globex/jobs/4002"),
            (captcha_job, "/globex/jobs/4003"),
            (signature_job, "/globex/jobs/4004"),
        ):
            await posting_repository.add(
                _seed_posting(job_id=job_id, apply_url=portal.url(path))
            )
        for document in _seed_documents(
            run_id=run_id, user_id=user_id, job_id=good_job
        ):
            await document_repository.add(document)

    app = create_app()
    # An ASGI transport rather than `TestClient`: every request runs on *this*
    # test's event loop, which is what lets a browser session opened during
    # one request still be usable during the next. That is also true of the
    # real server (uvicorn runs one loop), and is exactly the constraint
    # `ApplicationReviewSessions` documents.
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    try:
        # ---- 0. the auth gate is live, before a browser opens -------------
        unauthenticated = await client.post(f"/api/job-postings/{good_job}/autofill")
        assert unauthenticated.status_code == 401
        assert portal.submissions == []

        # ---- 1. fill the form ---------------------------------------------
        filled = await client.post(
            f"/api/job-postings/{good_job}/autofill", headers=auth
        )
        assert filled.status_code == 200, filled.text
        report = filled.json()

        assert report["ats_provider"] == "greenhouse"
        assert report["review_session_id"], "a filled form must be parked for review"
        assert report["requires_handoff"] is False
        assert report["can_be_submitted_here"] is True
        assert report["screenshot_png_base64"], "the reviewer gets proof of the form"
        review_id = report["review_session_id"]

        # The standard fields, from the profile.
        assert _field(report, "First Name *")["value"] == "Dana"
        assert _field(report, "Last Name *")["value"] == "Whitfield"
        assert _field(report, "Email *")["value"] == f"{user_id}@example.com"
        assert _field(report, "Phone")["value"] == "512-555-0148"
        assert _field(report, "Location (City)")["value"] == "Austin, Texas"
        assert (
            _field(report, "LinkedIn Profile")["value"]
            == "https://www.linkedin.com/in/danawhitfield"
        )
        # The name was split out of one stored field, so the reviewer is
        # pointed at it; the values read verbatim are not flagged.
        assert _field(report, "First Name *")["is_derived"] is True
        assert _field(report, "Email *")["is_derived"] is False

        # The documents: the resume as an uploaded PDF, the letter pasted.
        resume = _field(report, "Resume/CV *")
        assert resume["outcome"] == "attached"
        assert resume["value"] == "dana-whitfield-resume.pdf"
        assert _field(report, "Cover Letter")["value"] == COVER_LETTER_TEXT

        # The legal questions: answered exactly, and flagged for the
        # candidate to confirm before anything is sent.
        authorization = _field(
            report, "Are you legally authorized to work in the United States? *"
        )
        assert authorization["value"] == "Yes"
        assert authorization["sensitivity"] == "legal_attestation"
        assert authorization["requires_confirmation"] is True
        sponsorship = _field(
            report, "Will you now or in the future require visa sponsorship? *"
        )
        assert sponsorship["value"] == "No"
        assert sponsorship["requires_confirmation"] is True
        assert set(report["fields_awaiting_confirmation"]) == {
            authorization["field_id"],
            sponsorship["field_id"],
        }

        # EEO: untouched, flagged, and left for the candidate — even though
        # the profile holds an answer for both questions.
        for label in ("Gender", "Veteran status"):
            eeo = _field(report, label)
            assert eeo["outcome"] == "surfaced"
            assert eeo["value"] is None
            assert eeo["reason"] == "requires_candidate_answer"
            assert eeo["sensitivity"] == "voluntary_self_id"
            assert eeo["requires_confirmation"] is False

        # The company's own question: surfaced, and it will block submission.
        screening = _field(report, "Why do you want to work at Globex? *")
        assert screening["outcome"] == "surfaced"
        assert screening["reason"] == "unrecognized"
        assert report["unanswered_required_fields"] == [screening["field_id"]]

        # ---- 2. submission is refused until the candidate has acted -------
        unconfirmed = await client.post(
            f"/api/autofill-sessions/{review_id}/submit", headers=auth, json={}
        )
        assert unconfirmed.status_code == 409, unconfirmed.text
        assert sorted(unconfirmed.json()["detail"]["unconfirmed_fields"]) == sorted(
            [
                "Are you legally authorized to work in the United States? *",
                "Will you now or in the future require visa sponsorship? *",
            ]
        )
        assert portal.submissions == [], "nothing may reach the portal yet"

        confirmations = {
            "confirmed_field_ids": [
                authorization["field_id"],
                sponsorship["field_id"],
            ]
        }
        incomplete = await client.post(
            f"/api/autofill-sessions/{review_id}/submit",
            headers=auth,
            json=confirmations,
        )
        assert incomplete.status_code == 409, incomplete.text
        assert incomplete.json()["detail"]["unanswered_required_fields"] == [
            "Why do you want to work at Globex? *"
        ]
        assert portal.submissions == []

        # ---- 3. the candidate answers what only they can ------------------
        answered = await client.post(
            f"/api/autofill-sessions/{review_id}/fields/{screening['field_id']}",
            headers=auth,
            json={"value": SCREENING_ANSWER},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["unanswered_required_fields"] == []
        assert (
            _field(answered.json(), "Why do you want to work at Globex? *")[
                "answered_by_candidate"
            ]
            is True
        )

        # And discloses one EEO answer, of their own accord. The other is
        # left alone — which is also a decision, and one ApplyFlow honors by
        # sending it blank.
        gender_id = _field(report, "Gender")["field_id"]
        disclosed = await client.post(
            f"/api/autofill-sessions/{review_id}/fields/{gender_id}",
            headers=auth,
            json={"value": GENDER_ANSWER},
        )
        assert disclosed.status_code == 200, disclosed.text
        gender_after = _field(disclosed.json(), "Gender")
        assert gender_after["value"] == GENDER_ANSWER
        assert gender_after["answered_by_candidate"] is True
        assert gender_after["requires_confirmation"] is False

        # ---- 4. the candidate submits -------------------------------------
        submitted = await client.post(
            f"/api/autofill-sessions/{review_id}/submit",
            headers=auth,
            json=confirmations,
        )
        assert submitted.status_code == 200, submitted.text
        receipt = submitted.json()
        assert receipt["pressed_control"] == "Submit application"
        assert receipt["is_confirmed_sent"] is True
        assert receipt["outstanding_boundaries"] == []
        assert "received" in receipt["confirmation_excerpt"]
        assert receipt["screenshot_png_base64"]

        # What the portal actually received — the only account of this that
        # cannot be wrong.
        sent = portal.submissions_to("/globex/jobs/4001/submit")
        assert len(sent) == 1, "exactly one application, sent once"
        values = sent[0].values
        assert values["job_application[first_name]"] == "Dana"
        assert values["job_application[last_name]"] == "Whitfield"
        assert values["job_application[email]"] == f"{user_id}@example.com"
        assert values["job_application[phone]"] == "512-555-0148"
        assert values["job_application[location]"] == "Austin, Texas"
        assert (
            values["job_application[urls][LinkedIn]"]
            == "https://www.linkedin.com/in/danawhitfield"
        )
        # Newlines are compared normalized: HTML form submission rewrites a
        # textarea's line breaks to CRLF (the "API value" vs. "value" split in
        # the spec), so the bytes the portal receives differ from the stored
        # snapshot by exactly that and by nothing else. Asserting on the raw
        # value here would be asserting a browser detail, not the document.
        assert (
            values["job_application[cover_letter_text]"].replace("\r\n", "\n")
            == COVER_LETTER_TEXT
        )
        assert values["job_application[answers][why]"] == SCREENING_ANSWER
        assert values["job_application[answers][work_authorization]"] == "Yes"
        assert values["job_application[answers][sponsorship]"] == "No"

        # The EEO fields, which is the whole of criterion 3 in two lines: the
        # one the candidate answered carries their answer, and the one they
        # left alone is empty — even though the profile has an answer for it.
        assert values["job_application[eeo][gender]"] == GENDER_ANSWER
        assert values["job_application[eeo][veteran_status]"] == ""

        # The resume really was uploaded, as a real PDF.
        filename, content = sent[0].files["job_application[resume]"]
        assert filename == "dana-whitfield-resume.pdf"
        assert content.startswith(b"%PDF")

        # The review is finished: it cannot be submitted a second time.
        again = await client.post(
            f"/api/autofill-sessions/{review_id}/submit",
            headers=auth,
            json=confirmations,
        )
        assert again.status_code == 404
        assert len(portal.submissions_to("/globex/jobs/4001/submit")) == 1

        # ---- 5a. a login wall: nothing is filled at all -------------------
        login = await client.post(
            f"/api/job-postings/{login_job}/autofill", headers=auth
        )
        assert login.status_code == 200, login.text
        login_report = login.json()
        assert login_report["requires_handoff"] is True
        assert login_report["fields"] == [], (
            "a sign-in page is not the application form; nothing on it may be "
            "filled"
        )
        assert login_report["review_session_id"] is None
        assert login_report["can_be_submitted_here"] is False
        (login_boundary,) = login_report["boundaries"]
        assert login_boundary["kind"] == "login"
        assert login_boundary["stopped_autofill"] is True
        assert "password" in login_boundary["evidence"]
        assert login_boundary["instruction"].strip()
        assert login_report["screenshot_png_base64"]
        assert portal.submissions_to("/globex/jobs/4002/session") == []

        # ---- 5b. a CAPTCHA: filled, and not sendable from here ------------
        captcha = await client.post(
            f"/api/job-postings/{captcha_job}/autofill", headers=auth
        )
        assert captcha.status_code == 200, captcha.text
        captcha_report = captcha.json()
        # The form around the challenge is real, and filling it is most of
        # the value the candidate came for.
        assert _field(captcha_report, "First Name *")["value"] == "Dana"
        assert captcha_report["requires_handoff"] is True
        assert captcha_report["can_be_submitted_here"] is False
        (captcha_boundary,) = captcha_report["boundaries"]
        assert captcha_boundary["kind"] == "captcha"
        assert captcha_boundary["stopped_autofill"] is False
        assert captcha_boundary["blocks_submission"] is True

        captcha_submit = await client.post(
            f"/api/autofill-sessions/{captcha_report['review_session_id']}/submit",
            headers=auth,
            json={
                "confirmed_field_ids": captcha_report[
                    "fields_awaiting_confirmation"
                ]
            },
        )
        assert captcha_submit.status_code == 409, captcha_submit.text
        handoff = captcha_submit.json()["detail"]
        assert [item["kind"] for item in handoff["boundaries"]] == ["captcha"]
        assert handoff["apply_url"].startswith(f"http://{PORTAL_HOST}")
        assert "CAPTCHA" in handoff["boundaries"][0]["instruction"]
        assert portal.submissions_to("/globex/jobs/4003/submit") == []

        # ---- 5c. a signature: never signed for, never sent ----------------
        signature = await client.post(
            f"/api/job-postings/{signature_job}/autofill", headers=auth
        )
        assert signature.status_code == 200, signature.text
        signature_report = signature.json()
        signature_field = _field(signature_report, "Signature (type your full name) *")
        # The label names the candidate's full name, which ApplyFlow has on
        # file. Typing it here would be signing for them.
        assert signature_field["outcome"] == "surfaced"
        assert signature_field["value"] is None
        assert signature_field["reason"] == "requires_candidate_signature"
        assert _field(signature_report, "First Name *")["value"] == "Dana"
        (signature_boundary,) = signature_report["boundaries"]
        assert signature_boundary["kind"] == "signature"
        assert signature_report["can_be_submitted_here"] is False

        signature_submit = await client.post(
            f"/api/autofill-sessions/{signature_report['review_session_id']}/submit",
            headers=auth,
            json={},
        )
        assert signature_submit.status_code == 409, signature_submit.text
        assert [
            item["kind"]
            for item in signature_submit.json()["detail"]["boundaries"]
        ] == ["signature"]
        assert portal.submissions_to("/globex/jobs/4004/submit") == []

        # Across the whole run, exactly one application was submitted, and it
        # was the one a candidate pressed Submit on.
        assert len(portal.submissions) == 1

        # Printed for a `-s` run, because "what the portal received" is the
        # artifact this check exists to produce, and reading it is how a
        # reviewer confirms the assertions above describe the right thing.
        print("\n--- what the portal received ---")
        for name, value in sorted(values.items()):
            print(f"{name} = {value!r}" if value else f"{name} = <empty>")
        print(f"{'job_application[resume]'} = {filename} ({len(content)} bytes)")
    finally:
        # Close every browser this run opened, then the portal, then remove
        # the candidate. The seeded postings and document snapshots are left
        # in place deliberately, the same convention epics 03 and 04 follow:
        # neither repository exposes a delete, because a record of what was
        # sent must not be erasable.
        await shutdown_portal_automation()
        await client.aclose()
        await portal.stop()
        get_browser_automation.cache_clear()
        get_review_sessions.cache_clear()
        if previous_launch_args is None:
            os.environ.pop("BROWSER_LAUNCH_ARGS", None)
        else:
            os.environ["BROWSER_LAUNCH_ARGS"] = previous_launch_args
        get_settings.cache_clear()

        await dispose_engine()
        async with async_session_factory() as session:
            await SqlAlchemyProfileRepository(session).delete(profile.id)
