"""GenerationGuardAudit — the one place provenance-guard outcomes get
logged, so every generation flow reports fabrication attempts the same way.

Why it exists at all: a stripped line is the single most important
diagnostic signal in the generation pipeline. It means the model tried to
assert something about a real person that their data does not support, and
whoever is debugging needs the exact terms that failed, not a count. This
lives in the application layer because `ProvenanceGuard` is a pure domain
service and must stay free of logging (see `src/domain/CLAUDE.md`), while
both `GenerateTailoredResume` and `GenerateCoverLetter` need identical
reporting — one shared recorder rather than two drifting copies.

Log levels carry meaning: a stripped line is a WARNING because generation
misbehaved even though the request succeeded, while a clean run logs at
DEBUG so a healthy pipeline stays quiet.

On what gets written: the stripped line is logged verbatim. It reads like
candidate data but is the opposite — by definition nothing in the
provenance-backed record supports it, so it is model invention rather than
anything the candidate provided, and withholding it would leave the one
class of bug this pipeline exists to prevent undebuggable. Content that
*is* the candidate's (the surviving document) is never logged.
"""

from __future__ import annotations

import logging

from src.domain.services.provenance_guard import GuardedContent
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind

logger = logging.getLogger(__name__)


class GenerationGuardAudit:
    """Records what the provenance guard kept and removed."""

    @staticmethod
    def record(
        *,
        document_kind: GeneratedDocumentKind,
        user_id: str,
        job_posting_id: str,
        guarded: GuardedContent,
    ) -> None:
        """Log the outcome of guarding one generated document."""
        if guarded.is_clean:
            logger.debug(
                "provenance guard passed %s for user=%s job=%s (%d line(s), "
                "sources=%s)",
                document_kind.value,
                user_id,
                job_posting_id,
                len(guarded.lines),
                ",".join(source.value for source in guarded.backing_sources) or "none",
            )
            return

        logger.warning(
            "provenance guard stripped %d unsupported line(s) from %s for "
            "user=%s job=%s",
            len(guarded.violations),
            document_kind.value,
            user_id,
            job_posting_id,
        )
        for violation in guarded.violations:
            logger.warning(
                "provenance violation in %s for user=%s job=%s: "
                "unsupported terms %s in stripped line %r",
                document_kind.value,
                user_id,
                job_posting_id,
                ",".join(violation.unsupported_terms),
                violation.line,
            )
