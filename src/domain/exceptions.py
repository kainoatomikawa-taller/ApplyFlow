"""Domain-level exceptions.

These represent violations of business rules. They carry no knowledge of
HTTP, databases, or any framework — they are pure business concepts.
"""


class DomainError(Exception):
    """Base class for all domain errors."""


class InvalidValueError(DomainError):
    """Raised when a value object receives an invalid value."""


class BusinessRuleViolation(DomainError):
    """Raised when an operation would break an entity invariant."""


class ApplicationNotFoundError(DomainError):
    """Raised when a job application cannot be located."""

    def __init__(self, application_id: str) -> None:
        super().__init__(f"Job application '{application_id}' was not found.")
        self.application_id = application_id
