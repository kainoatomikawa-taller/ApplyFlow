"""Domain-level exceptions.

These represent violations of business rules. They carry no knowledge of
HTTP, databases, or any framework — they are pure business concepts.
"""


class DomainError(Exception):
    """Base class for all domain errors."""


class InvalidValueError(DomainError):
    """Raised when a value object receives an invalid value."""


class BusinessRuleViolationError(DomainError):
    """Raised when an operation would break an entity invariant."""


class ApplicationNotFoundError(DomainError):
    """Raised when a job application cannot be located."""

    def __init__(self, application_id: str) -> None:
        super().__init__(f"Job application '{application_id}' was not found.")
        self.application_id = application_id


class UnsupportedFileFormatError(DomainError):
    """Raised when an uploaded resume's content type isn't one ApplyFlow
    accepts. Carries only the content type — never a filename — so it's
    safe to surface directly in an HTTP response or log line."""

    def __init__(self, content_type: str) -> None:
        super().__init__(f"Unsupported resume file format: '{content_type}'.")
        self.content_type = content_type


class FileTooLargeError(DomainError):
    """Raised when an uploaded resume exceeds `Resume.MAX_SIZE_BYTES`."""

    def __init__(self, size_bytes: int, max_size_bytes: int) -> None:
        super().__init__(
            f"Resume file of {size_bytes} bytes exceeds the "
            f"{max_size_bytes}-byte limit."
        )
        self.size_bytes = size_bytes
        self.max_size_bytes = max_size_bytes


class ResumeNotFoundError(DomainError):
    """Raised when a resume cannot be located."""

    def __init__(self, resume_id: str) -> None:
        super().__init__(f"Resume '{resume_id}' was not found.")
        self.resume_id = resume_id


class JobPostingNotFoundError(DomainError):
    """Raised when a job posting cannot be located."""

    def __init__(self, job_posting_id: str) -> None:
        super().__init__(f"Job posting '{job_posting_id}' was not found.")
        self.job_posting_id = job_posting_id


class AnswerMemoryNotFoundError(DomainError):
    """Raised when a remembered answer cannot be located."""

    def __init__(self, answer_memory_id: str) -> None:
        super().__init__(f"Answer memory '{answer_memory_id}' was not found.")
        self.answer_memory_id = answer_memory_id


class ApplicationDocumentNotFoundError(DomainError):
    """Raised when a stored resume/cover-letter snapshot cannot be located
    by id. Carries only the id — never any of the document's content, which
    is sensitive (see `ApplicationDocument`)."""

    def __init__(self, document_id: str) -> None:
        super().__init__(f"Application document '{document_id}' was not found.")
        self.document_id = document_id


class NoStoredApplicationDocumentError(DomainError):
    """Raised when no snapshot of a given kind has ever been stored for a
    job posting — i.e. nothing was produced for it yet, so there is nothing
    to reuse. Distinct from `ApplicationDocumentNotFoundError`, which means
    a specific id does not resolve."""

    def __init__(self, job_posting_id: str, document_kind: str) -> None:
        super().__init__(
            f"No {document_kind} has been stored for job posting "
            f"'{job_posting_id}'."
        )
        self.job_posting_id = job_posting_id
        self.document_kind = document_kind


class DocumentSnapshotIntegrityError(DomainError):
    """Raised when a stored document's content no longer hashes to the
    digest recorded when it was written.

    A snapshot exists to state what was actually sent, so content that
    changed underneath it is a corrupted record, not a stale one: it is
    refused rather than returned as authentic. Carries only digests and the
    id — never the content — so it is safe to log.
    """

    def __init__(
        self, document_id: str, expected_digest: str, actual_digest: str
    ) -> None:
        super().__init__(
            f"Stored application document '{document_id}' does not match its "
            f"recorded content digest (expected {expected_digest}, "
            f"content hashes to {actual_digest})."
        )
        self.document_id = document_id
        self.expected_digest = expected_digest
        self.actual_digest = actual_digest


class TrackedApplicationNotFoundError(DomainError):
    """Raised when a tracked application cannot be located for this candidate.

    Deliberately one error for "no such application" and "not this
    candidate's": telling the two apart would confirm to a caller that some
    other user's application exists under an id they guessed. A status update
    is the operation most likely to be probed that way, since it names an id
    directly.

    Carries only the id — a tracked application's role and company are not
    sensitive, but there is no reason for an error to repeat them — so it is
    safe to log and to return.
    """

    def __init__(self, application_id: str) -> None:
        super().__init__(f"Tracked application '{application_id}' was not found.")
        self.application_id = application_id


class ApplicationReviewNotFoundError(DomainError):
    """Raised when a candidate's review of a filled application cannot be
    located.

    Carries only the id — never any answer, which is sensitive (see
    `ApplicationReview`) — so it is safe to log and to return.
    """

    def __init__(self, review_id: str) -> None:
        super().__init__(f"Application review '{review_id}' was not found.")
        self.review_id = review_id


class NoActiveApplicationReviewError(DomainError):
    """Raised when a job posting has no review still open for this candidate —
    nothing has been filled for it yet, or the last one was already submitted.

    Distinct from `ApplicationReviewNotFoundError`, which means a specific id
    does not resolve: this one means "there is nothing to review", and the
    remedy is to open a review rather than to look for a different id.
    """

    def __init__(self, job_posting_id: str) -> None:
        super().__init__(
            f"No application review is open for job posting '{job_posting_id}'."
        )
        self.job_posting_id = job_posting_id


class ReviewedAnswerNotFoundError(DomainError):
    """Raised when an edit addresses a field the review does not contain.

    Loud rather than silent: an edit that quietly landed nowhere would look to
    the candidate exactly like one that was saved.
    """

    def __init__(self, review_id: str, field_key: str) -> None:
        super().__init__(
            f"Application review '{review_id}' has no field '{field_key}'."
        )
        self.review_id = review_id
        self.field_key = field_key


class PortalHandoffNotFoundError(DomainError):
    """Raised when a hand-off to the candidate cannot be located by id.

    Carries only the id — never the resolution note, which is candidate free
    text (see `PortalHandoff`) — so it is safe to log and to return.
    """

    def __init__(self, handoff_id: str) -> None:
        super().__init__(f"Portal hand-off '{handoff_id}' was not found.")
        self.handoff_id = handoff_id


class ProfileNotFoundError(DomainError):
    """Raised when a candidate profile cannot be located."""

    def __init__(self, profile_id: str) -> None:
        super().__init__(f"Profile '{profile_id}' was not found.")
        self.profile_id = profile_id


class ProfileMissingContactInfoError(DomainError):
    """Raised when a new profile would be created without a full name or
    email — both required to identify the profile's owner. Parsing must
    never fabricate these, so if a resume doesn't state them and no
    profile already exists to attach parsed facts to, the operation is
    rejected rather than invented."""

    def __init__(self) -> None:
        super().__init__(
            "Cannot create a profile: no full name and email could be "
            "extracted from this resume, and none exists yet."
        )
