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
