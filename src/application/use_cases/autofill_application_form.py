"""AutofillApplicationForm use case — puts a browser on one posting's apply
URL, fills every standard field it can from the candidate's profile and
generated documents, and reports back everything it did not fill.

The flow
--------
1. Resolve the posting's `apply_url` to one of the three supported ATS
   platforms with `identify_ats_board`. Anything else is refused here, before
   a browser starts (`UnsupportedAtsFormError`).
2. Read the form once, and observe the page alongside it. Every handle in the
   plan belongs to that one snapshot.
3. Check for a human-only boundary (`scan_application_boundaries`). A login
   wall stops the pass here, before anything is typed.
4. Plan every field (`AtsFormFieldPlanner`) — pure, no I/O.
5. Execute the plan field by field, and screenshot the result.
6. Park the filled form for review, and hand back the report plus the id the
   candidate will submit through.

It does not submit
------------------
Nothing in this pass presses anything: it never asks the session for a
submit control, so it holds nothing pressable. What it produces is a filled
form and an honest account of it. Sending is a separate act, in a separate
use case, that requires the candidate's instruction and their confirmation
of every sensitive value (`SubmitApplicationForm`).

Where a boundary stops it
-------------------------
A **login wall** means the page in the browser is not the application form,
so filling it would type the candidate's details into a sign-in box. The
pass ends with an empty field list, the boundary, and a screenshot — and no
parked session, because there is nothing to review or submit.

A **CAPTCHA** or a **signature request** does not stop the filling. The form
around them is real and filling it is most of the value the candidate came
for. They are reported on the pass, and they are what makes
`can_be_submitted_here` false: the candidate finishes those in their own
browser.

Why one failed field does not fail the pass
-------------------------------------------
A form refusing one value (`RejectedFieldValueError`) or one element refusing
input (`FormFieldNotFillableError`) is recorded against that field and the
rest of the form still gets filled. Twenty correctly filled fields plus one
honest "the state dropdown wouldn't take 'California'" is worth far more to a
candidate than an exception that abandons the whole form — and the report
makes the gap impossible to miss.

`StaleFormFieldError` is the exception, and propagates. It means the page
changed underneath the snapshot, so every remaining handle is suspect too;
continuing would risk writing the candidate's phone number into whatever
field drifted into that position. The whole pass is abandoned and re-reading
the form is the remedy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.application.dtos.application_autofill_dtos import (
    APPLIED_OUTCOMES,
    ApplicationAutofillOutput,
    AutofillApplicationFormInput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.exceptions import (
    BrowserAutomationError,
    FormFieldNotFillableError,
    RejectedFieldValueError,
    UnsupportedAtsFormError,
)
from src.application.ports.browser_automation_port import (
    BrowserAutomationPort,
    BrowserSessionPort,
    FormField,
    FormFieldKind,
)
from src.application.ports.resume_pdf_renderer_port import ResumePdfRendererPort
from src.application.services.application_boundary_scanner import (
    scan_application_boundaries,
    to_boundary_output,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.services.ats_form_field_planner import (
    AtsFormFieldPlanner,
    FieldDisposition,
    PlannedField,
    SurfaceReason,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.services.ats_board_locator import (
    AtsBoardReference,
    identify_ats_board,
)
from src.domain.value_objects.application_boundary import ApplicationBoundary
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind

logger = logging.getLogger(__name__)

_NON_FILENAME_RE = re.compile(r"[^a-z0-9]+")

#: What each attachable document is called in a filename and in PDF title
#: metadata — this is what a recruiter sees in their downloads folder.
_DOCUMENT_LABELS: dict[GeneratedDocumentKind, str] = {
    GeneratedDocumentKind.TAILORED_RESUME: "resume",
    GeneratedDocumentKind.COVER_LETTER: "cover-letter",
}


class AutofillApplicationForm:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        profile_repository: ProfileRepository,
        document_repository: ApplicationDocumentRepository,
        browser: BrowserAutomationPort,
        pdf_renderer: ResumePdfRendererPort,
        review_sessions: ApplicationReviewSessions,
        planner: AtsFormFieldPlanner | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._profile_repository = profile_repository
        self._document_repository = document_repository
        self._browser = browser
        self._pdf_renderer = pdf_renderer
        self._review_sessions = review_sessions
        self._planner = planner or AtsFormFieldPlanner()

    async def execute(
        self, dto: AutofillApplicationFormInput
    ) -> ApplicationAutofillOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        board = identify_ats_board(posting.apply_url)
        if board is None:
            raise UnsupportedAtsFormError(
                job_posting_id=posting.id, apply_url=posting.apply_url
            )

        profile = await self._profile_repository.get_by_user_id(dto.user_id)
        if profile is None:
            raise ProfileNotFoundError(dto.user_id)

        session = await self._browser.open(posting.apply_url)
        # Not `async with`: a pass that fills a form leaves its session open
        # for the candidate to review and submit through, and only the paths
        # that produce nothing to review close it here. Every failure path
        # closes it — a browser context nobody is reviewing is a leak.
        parked = False
        try:
            fields = await session.read_fields()
            boundaries = await scan_application_boundaries(
                session,
                field_labels=tuple(item.label for item in fields),
                has_password_field=any(
                    item.kind is FormFieldKind.PASSWORD for item in fields
                ),
            )
            blocking = [boundary for boundary in boundaries if boundary.stops_autofill]
            if blocking:
                # Reported, not raised. The candidate asked what ApplyFlow
                # could do with this form and the answer — "nothing, and here
                # is why, and here is what you do" — is a result.
                logger.info(
                    "Autofill stopped at a %s boundary before filling "
                    "anything (job_posting_id=%s).",
                    blocking[0].kind.value,
                    posting.id,
                )
                return await self._nothing_to_review(
                    session, posting_id=posting.id, board=board, boundaries=boundaries
                )

            if not fields:
                # The page presented no fillable field at all (see
                # `read_fields`): a dead posting or an interstitial. There is
                # nothing to fill, nothing to review, and nothing to submit —
                # so no browser is held open waiting for a candidate who has
                # nothing to do with it.
                return await self._nothing_to_review(
                    session, posting_id=posting.id, board=board, boundaries=boundaries
                )

            planned = self._planner.plan(
                fields, provider=board.provider, profile=profile
            )

            # Built per pass, so a form asking for the same document twice
            # reads and renders it once and cannot end up sending two
            # versions of it.
            documents = _DocumentSource(
                repository=self._document_repository,
                renderer=self._pdf_renderer,
                profile=profile,
                job_posting_id=posting.id,
            )
            results = [
                await self._execute_field(session, item, documents=documents)
                for item in planned
            ]

            review = await self._review_sessions.park(
                user_id=dto.user_id,
                job_posting_id=posting.id,
                apply_url=session.current_url,
                ats_provider=board.provider.value,
                session=session,
                fields=results,
                screenshot_png=await self._capture_screenshot(session),
                boundaries=[to_boundary_output(boundary) for boundary in boundaries],
            )
            parked = True
            return review.to_output()
        finally:
            if not parked:
                await session.close()

    async def _nothing_to_review(
        self,
        session: BrowserSessionPort,
        *,
        posting_id: str,
        board: AtsBoardReference,
        boundaries: tuple[ApplicationBoundary, ...],
    ) -> ApplicationAutofillOutput:
        """A report with no review session behind it.

        Used for the two passes that produce nothing a candidate can act on
        inside ApplyFlow: a login wall, and a page with no form on it. Both
        still carry the screenshot, because "here is what we saw" is the
        difference between an explanation and an assertion.
        """
        return ApplicationAutofillOutput(
            job_posting_id=posting_id,
            apply_url=session.current_url,
            ats_provider=board.provider.value,
            fields=[],
            screenshot_png=await self._capture_screenshot(session),
            boundaries=[to_boundary_output(boundary) for boundary in boundaries],
        )

    # ---- Executing one planned field ----------------------------------------

    async def _execute_field(
        self,
        session: BrowserSessionPort,
        item: PlannedField,
        *,
        documents: _DocumentSource,
    ) -> AutofilledFieldOutput:
        if item.disposition is FieldDisposition.FILL:
            # The planner always sets `value` alongside FILL; defaulting
            # rather than asserting keeps a malformed plan from filling a
            # form with the string "None".
            return await self._fill(session, item, value=item.value or "")

        if item.document_kind is not None:
            return await self._execute_document_field(
                session, item, document_kind=item.document_kind, documents=documents
            )

        # SURFACE, and the total fallback: anything the planner did not give
        # enough to act on is reported rather than attempted.
        return self._surfaced(item, item.surface_reason)

    async def _execute_document_field(
        self,
        session: BrowserSessionPort,
        item: PlannedField,
        *,
        document_kind: GeneratedDocumentKind,
        documents: _DocumentSource,
    ) -> AutofilledFieldOutput:
        """Give this field the document it asked for, in the shape it wants.

        Only the shape the field actually needs is produced: a paste box
        never triggers a PDF render, which is the expensive half.
        """
        if item.disposition is FieldDisposition.FILL_DOCUMENT_TEXT:
            text = await documents.text(document_kind)
            if text is None:
                return self._surfaced(item, SurfaceReason.DOCUMENT_NOT_GENERATED)
            return await self._fill(session, item, value=text)

        attachment = await documents.pdf(document_kind)
        if attachment is None:
            return self._surfaced(item, SurfaceReason.DOCUMENT_NOT_GENERATED)
        return await self._attach(session, item, attachment=attachment)

    async def _fill(
        self, session: BrowserSessionPort, item: PlannedField, *, value: str
    ) -> AutofilledFieldOutput:
        too_long = self._exceeds_max_length(item.field, value)
        if too_long is not None:
            return self._surfaced(item, SurfaceReason.VALUE_TOO_LONG, detail=too_long)

        try:
            await session.fill(item.field.handle, value)
        except RejectedFieldValueError as exc:
            return self._outcome(
                item,
                FieldAutofillOutcome.NOT_ACCEPTED,
                value=value,
                detail=f"The form accepts: {exc.accepted}.",
            )
        except FormFieldNotFillableError as exc:
            return self._outcome(
                item, FieldAutofillOutcome.FAILED, value=value, detail=exc.reason
            )
        return self._outcome(item, FieldAutofillOutcome.FILLED, value=value)

    async def _attach(
        self,
        session: BrowserSessionPort,
        item: PlannedField,
        *,
        attachment: _Attachment,
    ) -> AutofilledFieldOutput:
        try:
            await session.attach_file(
                item.field.handle,
                filename=attachment.filename,
                content=attachment.content,
            )
        except FormFieldNotFillableError as exc:
            return self._outcome(
                item,
                FieldAutofillOutcome.FAILED,
                value=attachment.filename,
                detail=exc.reason,
            )
        return self._outcome(
            item, FieldAutofillOutcome.ATTACHED, value=attachment.filename
        )

    @staticmethod
    def _exceeds_max_length(field: FormField, value: str) -> str | None:
        """Say so if `value` is longer than the portal's declared limit.

        Refusing beats truncating. A resume or cover letter clipped to fit
        ends mid-sentence, and it still goes to a recruiter with the
        candidate's name on it — so the field is surfaced and the candidate
        decides what to cut.
        """
        limit = field.max_length
        if limit is None or len(value) <= limit:
            return None
        return (
            f"The value is {len(value)} characters but this field accepts at "
            f"most {limit}."
        )

    # ---- Result shaping ------------------------------------------------------

    @staticmethod
    async def _capture_screenshot(session: BrowserSessionPort) -> bytes | None:
        """The filled form as PNG, or None if the capture failed.

        A failed screenshot costs the reviewer their proof, not their work —
        the form is already filled and the report is already accurate — so it
        is reported as absent rather than thrown after the fact.
        """
        try:
            return await session.screenshot()
        except BrowserAutomationError:
            return None

    @classmethod
    def _surfaced(
        cls,
        item: PlannedField,
        reason: SurfaceReason | None,
        *,
        detail: str | None = None,
    ) -> AutofilledFieldOutput:
        return cls._outcome(
            item,
            FieldAutofillOutcome.SURFACED,
            reason=reason.value if reason else None,
            detail=detail,
        )

    @staticmethod
    def _outcome(
        item: PlannedField,
        outcome: FieldAutofillOutcome,
        *,
        value: str | None = None,
        reason: str | None = None,
        detail: str | None = None,
    ) -> AutofilledFieldOutput:
        sensitivity = item.sensitivity
        return AutofilledFieldOutput(
            # The browser handle doubles as the field's id in the review
            # step, so answering or confirming a field addresses the same
            # element the plan did — and stops working the moment that
            # element does (see `AutofilledFieldOutput.field_id`).
            field_id=item.field.handle,
            label=item.field.label,
            kind=item.field.kind.value,
            required=item.field.required,
            outcome=outcome.value,
            slot=item.slot.value if item.slot else None,
            value=value,
            is_derived=item.is_derived,
            reason=reason,
            detail=detail,
            is_sensitive=sensitivity is not None,
            sensitivity=sensitivity.value if sensitivity is not None else None,
            # Only a value that actually reached the form needs approving.
            # A sensitive field the plan meant to fill but the portal refused
            # is already surfaced for the candidate to answer, so asking them
            # to *confirm* it too would be one gate too many pointing at the
            # same field.
            requires_confirmation=(
                item.requires_confirmation and outcome in APPLIED_OUTCOMES
            ),
        )


@dataclass(frozen=True)
class _Attachment:
    """A stored document rendered as a file, ready to upload."""

    filename: str
    content: bytes


class _DocumentSource:
    """The generated documents one autofill pass needs, fetched and rendered
    at most once each.

    Scoped to a single pass rather than to the use case, so nothing is
    carried between candidates or between jobs. Both shapes a form can ask
    for come from the same snapshot read, which is what makes it impossible
    for an uploaded PDF and a pasted body to disagree; and the PDF render —
    the expensive half — happens only if some field actually takes a file.
    """

    def __init__(
        self,
        *,
        repository: ApplicationDocumentRepository,
        renderer: ResumePdfRendererPort,
        profile: UserProfile,
        job_posting_id: str,
    ) -> None:
        self._repository = repository
        self._renderer = renderer
        self._profile = profile
        self._job_posting_id = job_posting_id
        self._documents: dict[GeneratedDocumentKind, ApplicationDocument | None] = {}
        self._attachments: dict[GeneratedDocumentKind, _Attachment] = {}

    async def text(self, document_kind: GeneratedDocumentKind) -> str | None:
        """The document's exact stored text, or None if none was generated."""
        document = await self._document(document_kind)
        return document.content if document is not None else None

    async def pdf(self, document_kind: GeneratedDocumentKind) -> _Attachment | None:
        """The document as an uploadable PDF, or None if none was generated."""
        cached = self._attachments.get(document_kind)
        if cached is not None:
            return cached

        document = await self._document(document_kind)
        if document is None:
            return None

        label = _DOCUMENT_LABELS[document_kind]
        attachment = _Attachment(
            filename=f"{_filename_stem(self._profile.full_name)}-{label}.pdf",
            content=self._renderer.render(
                document.content, title=f"{self._profile.full_name} — {label}"
            ),
        )
        self._attachments[document_kind] = attachment
        return attachment

    async def _document(
        self, document_kind: GeneratedDocumentKind
    ) -> ApplicationDocument | None:
        """The newest stored snapshot of this kind for this job.

        None is an ordinary state — the candidate has not run generation for
        this job yet — so it is cached like any other answer rather than
        re-queried for every field that asks.
        """
        if document_kind in self._documents:
            return self._documents[document_kind]

        document = await self._repository.get_latest(
            user_id=self._profile.user_id,
            job_posting_id=self._job_posting_id,
            document_kind=document_kind,
        )
        self._documents[document_kind] = document
        return document


def _filename_stem(full_name: str) -> str:
    """A safe filename stem from the candidate's name.

    The filename crosses into a multipart upload and lands in a recruiter's
    downloads folder, so it is reduced to lowercase alphanumerics and
    hyphens. A name with nothing left after that (scripts this rule cannot
    transliterate) falls back to a neutral stem rather than producing an
    empty or punctuation-only filename.
    """
    stem = _NON_FILENAME_RE.sub("-", full_name.lower()).strip("-")
    return stem or "candidate"
