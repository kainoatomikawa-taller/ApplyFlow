"""Application-layer exceptions.

These wrap orchestration failures that are not pure business-rule
violations (which belong in the domain layer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    # Imported under TYPE_CHECKING so this module keeps importing nothing at
    # runtime. `ApplicationHandoffRequiredError` carries the DTO a caller
    # will render, rather than a domain value object the interface layer
    # would then have to know how to map.
    from src.application.dtos.application_autofill_dtos import (
        ApplicationBoundaryOutput,
    )


class ApplicationError(Exception):
    """Base class for application-layer errors."""


class UseCaseError(ApplicationError):
    """Raised when a use case cannot complete for a non-domain reason."""


class ExternalServiceError(ApplicationError):
    """Raised when an outbound port (LLM, queue, etc.) fails."""


class AuthenticationError(ApplicationError):
    """Raised when a bearer token cannot be verified as the authenticated user."""


class TextExtractionError(ApplicationError):
    """Raised when an uploaded resume's content cannot be parsed into text
    (e.g. a corrupt PDF, a DOCX with no readable body, or a non-UTF-8
    "plain text" file)."""


class DocumentRenderError(ApplicationError):
    """Raised when a generated document cannot be rendered into its file
    format (see `ResumePdfRendererPort`)."""


class DocumentVersionConflictError(ApplicationError):
    """Raised when a sent-document snapshot could not be stored because
    another one already claims that version for the same job and kind.

    Snapshots are numbered from the count already stored (see
    `ApplicationDocumentArchive`), so a collision means two generations for
    the same job ran concurrently and both read the same count. Retrying
    the generation is the resolution; overwriting the existing snapshot is
    not, since it records a document that was already produced.
    """

    def __init__(self, document_kind: str, job_posting_id: str, version: int) -> None:
        self.document_kind = document_kind
        self.job_posting_id = job_posting_id
        self.version = version
        super().__init__(
            f"Version {version} of the {document_kind} for job posting "
            f"'{job_posting_id}' is already stored; a concurrent generation "
            "claimed it first."
        )


class BrowserAutomationError(ApplicationError):
    """Base class for failures driving a browser over an application
    portal (see `BrowserAutomationPort`)."""


class BrowserNavigationError(BrowserAutomationError):
    """Raised when a session could not load the application form at an
    apply URL — a timeout, a DNS/connection failure, or the portal
    answering with an error status.

    Distinct from `ApplyUrlCheckerPort`'s `LinkCheckOutcome`, which exists
    precisely so a dead link is *data* rather than an exception. That port
    is asked "is this link still alive?", where a failure is the answer.
    This one is asked "put a browser on this form so I can fill it", where
    a failure means the caller's actual goal is unreachable — so it
    raises, and a caller that wants to reclassify the posting as dead does
    so through the checker, not by catching this.
    """

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Could not load the application form at {url}: {reason}")


class BrowserSessionClosedError(BrowserAutomationError):
    """Raised when a browser session is used after being closed."""


class StaleFormFieldError(BrowserAutomationError):
    """Raised when a field handle does not identify a field on the page as
    it is currently loaded — either it was never minted by this session's
    latest `read_fields()`, or the page changed underneath the snapshot so
    the handle now points at a different field (or none).

    One error covers both because the remedy is identical: re-read the
    form. Failing here is the whole reason handles are verified before use
    — silently writing into whichever field drifted into that position is
    how a candidate's salary expectation ends up in a diversity question.
    """

    def __init__(self, handle: str, reason: str) -> None:
        self.handle = handle
        self.reason = reason
        super().__init__(
            f"Form field '{handle}' is no longer addressable ({reason}). "
            "Call read_fields() again to re-snapshot the form."
        )


class FormFieldNotFillableError(BrowserAutomationError):
    """Raised when a field exists and is correctly addressed, but the
    requested operation does not apply to it (writing text into a file
    input, attaching a file to a text box) or the element refused to
    accept input at all (obscured by an overlay, detached mid-write).

    A caller holding the `FormField` can rule out the first case before
    ever calling — the field's `kind` says which operation applies.
    """

    def __init__(self, handle: str, reason: str) -> None:
        self.handle = handle
        self.reason = reason
        super().__init__(f"Form field '{handle}' could not be filled: {reason}")


class RejectedFieldValueError(BrowserAutomationError):
    """Raised when a field is fillable but cannot represent the given
    value — a value that matches none of a select's options, or one that
    isn't recognizable as a yes/no for a checkbox.

    Deliberately not a near-miss match: on a job application, quietly
    picking the option closest to what was asked for is worse than
    refusing, so the caller is told which values the field would accept
    and gets to choose.
    """

    def __init__(self, handle: str, value: str, accepted: str) -> None:
        self.handle = handle
        self.value = value
        self.accepted = accepted
        super().__init__(
            f"Form field '{handle}' rejected value '{value}'. Accepts: {accepted}."
        )


<<<<<<< HEAD
class SubmitControlNotPressableError(BrowserAutomationError):
    """Raised when a form's submit control was located but would not accept
    the press — obscured by an overlay or a cookie banner, disabled between
    the snapshot and the press, or detached mid-click.

    Deliberately distinct from a submission the portal *rejected*: nothing
    was sent here, so the candidate's application is exactly where it was
    and retrying is safe. A press that went through and came back with
    validation errors is not this error; it is a page for the candidate to
    read.
    """

    def __init__(self, handle: str, reason: str) -> None:
        self.handle = handle
        self.reason = reason
        super().__init__(f"Submit control '{handle}' could not be pressed: {reason}")
=======
class HumanOnlyFieldError(BrowserAutomationError):
    """Raised when something tried to write into a field only the candidate
    may fill — a password, a signature, a CAPTCHA answer.

    Not a variant of `FormFieldNotFillableError`, which means "this element
    would not take input". This field would take input perfectly well;
    ApplyFlow refuses to give it any. That is the non-negotiable rule the
    browser harness enforces at the point where typing happens, so it holds
    even when the caller asking for the write is a model that decided the
    field looked ordinary (see `HumanOnlyFieldPolicy`).

    There is no override, no force flag, and no retry that changes the
    answer: the remedy is a hand-off to the candidate (`PortalHandoff`), and
    `boundary` says which kind. Carries no value — the whole point is that
    nothing was written, and echoing the attempted value would put a
    credential in a log line.
    """

    def __init__(self, handle: str, boundary: str, field_label: str = "") -> None:
        self.handle = handle
        self.boundary = boundary
        self.field_label = field_label
        described = f" ('{field_label}')" if field_label else ""
        super().__init__(
            f"Form field '{handle}'{described} is a '{boundary}' boundary: "
            "only the candidate may fill it. ApplyFlow never solves CAPTCHAs, "
            "creates accounts, or enters passwords — hand off to the user "
            "instead."
        )
>>>>>>> origin/main


class UnsupportedAtsFormError(ApplicationError):
    """Raised when a posting's apply URL is not one of the ATS platforms
    field mapping covers (Greenhouse, Lever, Ashby).

    Coverage is scoped on purpose, and this is where the scope is enforced:
    the field-mapping rules encode how those three platforms name and label
    their controls, and a dynamic multi-step portal (Workday above all) does
    not resemble them. Reading one with these rules would not fail — it
    would confidently fill the wrong fields on a real application. So an
    unrecognized portal is refused before a browser is ever opened, and the
    candidate applies by hand.

    Carries the URL so a caller can tell the candidate where to go, and the
    posting id so the refusal can be logged without the URL.
    """

    def __init__(self, job_posting_id: str, apply_url: str) -> None:
        self.job_posting_id = job_posting_id
        self.apply_url = apply_url
        super().__init__(
            f"The application form at {apply_url} is not on a supported ATS "
            "platform. Field mapping covers Greenhouse, Lever, and Ashby; "
            "this posting has to be applied to by hand."
        )


class ReviewSessionNotFoundError(ApplicationError):
    """Raised when a parked review session cannot be produced for a caller —
    it never existed, it expired and its browser was closed, it was already
    submitted or discarded, or it belongs to a different candidate.

    One error for all of those on purpose. A caller holding a review session
    id has exactly one remedy in every case (run the autofill again), and
    distinguishing "expired" from "not yours" would tell an unauthorized
    caller that the id is real.
    """

    def __init__(self, review_session_id: str) -> None:
        self.review_session_id = review_session_id
        super().__init__(
            f"Review session '{review_session_id}' is not available. It may "
            "have expired, already been submitted, or never existed — run the "
            "autofill again to get a fresh one."
        )


class ReviewFieldNotFoundError(ApplicationError):
    """Raised when a field id does not name a field on the parked form."""

    def __init__(self, review_session_id: str, field_id: str) -> None:
        self.review_session_id = review_session_id
        self.field_id = field_id
        super().__init__(
            f"Field '{field_id}' is not part of review session "
            f"'{review_session_id}'."
        )


class ApplicationHandoffRequiredError(ApplicationError):
    """Raised when submitting is refused because the page carries a
    human-only check (see `ApplicationBoundary`).

    Not a failure of the flow — the point of it. A CAPTCHA or a signature
    request means the rest of this application is the candidate's to
    complete, and the exception carries what was found plus what to tell
    them, so the refusal arrives with an instruction rather than as a dead
    end.
    """

    def __init__(
        self, apply_url: str, boundaries: tuple[ApplicationBoundaryOutput, ...]
    ) -> None:
        self.apply_url = apply_url
        self.boundaries = boundaries
        super().__init__(
            "This application cannot be submitted through ApplyFlow: "
            f"{_describe_boundaries(boundaries)}. Finish it yourself at "
            f"{apply_url}."
        )


class UnconfirmedSensitiveFieldsError(ApplicationError):
    """Raised when submission was requested while sensitive values ApplyFlow
    filled are still unapproved.

    These are legal declarations written from the candidate's stored record
    — work authorization, sponsorship, visa status — and the candidate is
    the one accountable for asserting them to this employer. The gate is
    unconditional: there is no "submit anyway".
    """

    def __init__(self, labels: tuple[str, ...]) -> None:
        self.labels = labels
        listed = ", ".join(f"'{label}'" for label in labels) or "some fields"
        super().__init__(
            f"These answers need your confirmation before the application can "
            f"be sent: {listed}."
        )


class IncompleteApplicationError(ApplicationError):
    """Raised when submission was requested with required fields still
    unanswered.

    Refused here rather than sent for the portal to refuse, because a failed
    submission on some portals burns the application: the page reloads with
    the uploads dropped and the answers cleared. The fields are named so the
    candidate can answer them and submit again.
    """

    def __init__(self, labels: tuple[str, ...]) -> None:
        self.labels = labels
        listed = ", ".join(f"'{label}'" for label in labels) or "some fields"
        super().__init__(
            f"The form still needs these required answers before it can be "
            f"sent: {listed}."
        )


class SubmitControlUnavailableError(ApplicationError):
    """Raised when the form offers no control this harness can press, or the
    one that was named is not on the page.

    The empty case is a real portal shape, not a bug: a form that submits
    from script behind a plain `<button type="button">` exposes nothing that
    submits in the HTML sense. Pressing the nearest thing that looks like a
    button on a real job application is not an acceptable fallback, so the
    candidate is told to finish in their own browser.
    """

    def __init__(self, reason: str, *, available: tuple[str, ...] = ()) -> None:
        self.reason = reason
        self.available = available
        listed = ", ".join(f"'{label}'" for label in available)
        detail = f" The form offers: {listed}." if available else ""
        super().__init__(f"This form cannot be submitted here: {reason}.{detail}")


class AmbiguousSubmitControlError(ApplicationError):
    """Raised when a form offers several ways to send it and the caller did
    not say which.

    Guessing is not available. "Submit application" and "Submit and create an
    account" are both submissions, and choosing for the candidate would pick
    a side effect they never agreed to.
    """

    def __init__(self, available: tuple[str, ...]) -> None:
        self.available = available
        listed = ", ".join(f"'{label}'" for label in available)
        super().__init__(
            f"This form offers more than one way to submit ({listed}); name "
            "the one to press."
        )


def _describe_boundaries(boundaries: tuple[ApplicationBoundaryOutput, ...]) -> str:
    """Summarize boundaries for an exception message."""
    kinds = [boundary.kind for boundary in boundaries]
    return ", ".join(kinds) if kinds else "a check only you can complete"


class UnattestedGenerationError(ApplicationError):
    """Raised when nothing a generator produced survived the provenance
    guard as an attested claim (see `GuardedContent.has_attested_content`).

    Failing loudly instead of returning the husk that's left: a resume of
    bare section headings, or a cover letter that only says the candidate
    is interested, is not a document a candidate should be handed as
    finished work. It means either the model fabricated nearly everything
    or the profile is too thin to write from — both of which the caller has
    to be told, not shown as an empty page.

    Carries `unsupported_terms` (every term that failed, deduplicated
    across violations) so a caller can explain *why* without re-running
    the guard.
    """

    def __init__(self, document_kind: str, unsupported_terms: tuple[str, ...]) -> None:
        self.document_kind = document_kind
        self.unsupported_terms = unsupported_terms
        detail = ", ".join(unsupported_terms) if unsupported_terms else "none recorded"
        super().__init__(
            f"No attested content survived provenance checks for {document_kind}. "
            f"Unsupported terms: {detail}."
        )
