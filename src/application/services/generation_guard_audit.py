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

On what gets written: the unsupported *terms* are logged, and the stripped
line is not. This reverses an earlier decision here, which logged the line
verbatim on the reasoning that nothing in the provenance-backed record
supports it, so it must be model invention rather than candidate data.

That reasoning does not hold, and the gap is worth stating so it is not
re-argued: the guard strips a line because the *claim* is unsupported, which
says nothing about the rest of the words in it. "Sarah Okonkwo led a team of
40 at Initech" is stripped for the team of 40; the name in front of it is
real, and logging the line published it (Epic 07 — no PII in logs).

Little is lost, because the actionable signal was never the prose. This
module's whole reason for existing is that a debugger needs "the exact terms
that failed, not a count" — and `violation.unsupported_terms` *is* those
terms, logged in full. The document kind, the job, and the count come with
it. Content that is the candidate's own (the surviving document) was never
logged and still is not.
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
        # Numbered by position in the violation list rather than by document
        # line: `ProvenanceViolation` carries no line number, and inventing one
        # would mean handling the stripped text here, which is the thing this
        # is avoiding.
        for index, violation in enumerate(guarded.violations, start=1):
            logger.warning(
                "provenance violation %d/%d in %s for user=%s job=%s: "
                "unsupported terms %s",
                index,
                len(guarded.violations),
                document_kind.value,
                user_id,
                job_posting_id,
                ",".join(violation.unsupported_terms),
            )
