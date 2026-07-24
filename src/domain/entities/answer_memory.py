"""AnswerMemory entity — a candidate's remembered answer to an application
question, so it isn't re-asked on the next application.

Each record pairs the question text with its vector embedding (used for
semantic matching in a later epic — this entity is only the storage
foundation, not the retrieval itself) and the candidate's answer. Every
record's provenance is always `ANSWER`: an `AnswerMemory` only ever comes
into existence because a candidate actually answered a question, so unlike
`WorkHistoryEntry`/`EducationEntry`/`Skill` (which can come from a parsed
resume or manual entry too) there is no other legitimate source for one.

SENSITIVE: this store has no fixed schema of fields the way
`WorkAuthorization`/`EeoSelfIdentification` do — it holds free-text answers
to whatever an application asked, which can easily and unpredictably
include salary expectations, disability accommodations, visa/citizenship
status, or other data those two entities exist specifically to protect.
`SENSITIVE = True` here (mirrored on `AnswerMemoryModel`, see that class's
docstring) is the conservative default until a per-answer classifier
exists — see Epic 07's encryption/restricted-access work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AnswerMemory:
    """One remembered question/answer pair, plus the embedding of its
    question text."""

    SENSITIVE: ClassVar[bool] = True

    id: str
    user_id: str
    question_text: str
    answer_text: str
    embedding: list[float]
    source: ProvenanceSource
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("AnswerMemory requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("AnswerMemory requires a non-empty user_id.")
        if not self.question_text.strip():
            raise InvalidValueError("question_text cannot be empty.")
        if not self.answer_text.strip():
            raise InvalidValueError("answer_text cannot be empty.")
        if not self.embedding:
            raise InvalidValueError("AnswerMemory requires a non-empty embedding.")
        if not all(isinstance(v, (int, float)) for v in self.embedding):
            raise InvalidValueError("embedding must contain only numbers.")
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError("AnswerMemory requires a valid ProvenanceSource.")
        if self.source != ProvenanceSource.ANSWER:
            raise InvalidValueError(
                "AnswerMemory must be tagged with ProvenanceSource.ANSWER — "
                f"got '{self.source}'."
            )
