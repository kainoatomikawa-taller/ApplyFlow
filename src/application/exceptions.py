"""Application-layer exceptions.

These wrap orchestration failures that are not pure business-rule
violations (which belong in the domain layer).
"""


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
