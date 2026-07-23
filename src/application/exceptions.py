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
