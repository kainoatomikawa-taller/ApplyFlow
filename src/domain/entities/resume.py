"""Resume entity — a candidate's uploaded resume file.

An entity has identity and a lifecycle. It protects its own invariants:
which file formats are acceptable and how large a file may be are business
rules, so they're enforced here — never in a controller or use case.

`storage_key` and `extracted_text` are populated by the use case (the raw
bytes and their parsed text are produced by ports the domain knows nothing
about), but the entity still owns the rule that a resume can't exist
without them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.exceptions import (
    FileTooLargeError,
    InvalidValueError,
    UnsupportedFileFormatError,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Resume:
    """A single resume file uploaded by a candidate, plus its extracted text."""

    #: MIME types ApplyFlow accepts for a resume upload.
    ALLOWED_CONTENT_TYPES = frozenset(
        {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        }
    )
    #: 10 MiB — comfortably above any real resume, small enough to bound
    #: storage and parsing cost.
    MAX_SIZE_BYTES = 10 * 1024 * 1024

    id: str
    user_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    extracted_text: str
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("Resume requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("Resume requires a non-empty user_id.")
        if not self.original_filename.strip():
            raise InvalidValueError("Resume requires a non-empty original_filename.")
        if not self.storage_key:
            raise InvalidValueError("Resume requires a non-empty storage_key.")
        Resume.ensure_supported_format(self.content_type)
        Resume.ensure_within_size_limit(self.size_bytes)

    # ---- Business rules, exposed as class-level checks so a use case can
    # validate an upload *before* paying the cost of text extraction or
    # storage, while still sharing one definition with __post_init__. ------

    @staticmethod
    def ensure_supported_format(content_type: str) -> None:
        if content_type not in Resume.ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileFormatError(content_type)

    @staticmethod
    def ensure_within_size_limit(size_bytes: int) -> None:
        if size_bytes <= 0 or size_bytes > Resume.MAX_SIZE_BYTES:
            raise FileTooLargeError(size_bytes, Resume.MAX_SIZE_BYTES)
