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
