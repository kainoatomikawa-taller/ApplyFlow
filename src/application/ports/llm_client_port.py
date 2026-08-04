"""LlmClientPort — the single outbound abstraction for LLM access.

Every feature that needs a completion from a large language model depends
on this port, never on a provider SDK directly. The infrastructure layer
implements it once (see `AnthropicLlmClient`); use cases stay ignorant of
which model or provider answers the call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class LlmTaskType(StrEnum):
    """The kind of work a prompt is for — never a model name.

    Callers pick one of these; `TASK_TYPE_TIERS` below is the single place
    that decides which cost tier answers each task type. The
    infrastructure implementation only has to know how to turn a tier
    into a concrete model (see `AnthropicLlmClient`), so cost control is
    enforced in one place regardless of call site.
    """

    EXTRACTION = "extraction"
    MATCHING = "matching"
    PARSING = "parsing"
    RESUME_WRITING = "resume_writing"
    COVER_LETTER_WRITING = "cover_letter_writing"


class LlmModelTier(StrEnum):
    """A cost/capability tier a task type routes to.

    CHEAP is the fast, inexpensive model (Haiku); STRONG is the more
    capable, more expensive one (Sonnet). Which concrete model backs each
    tier is an infrastructure/config concern, not an application one.
    """

    CHEAP = "cheap"
    STRONG = "strong"


#: Default task-type -> tier routing. Extraction/matching/parsing are
#: high-volume, low-ambiguity tasks that don't need the stronger model;
#: writing a resume analysis or cover letter benefits from it.
TASK_TYPE_TIERS: dict[LlmTaskType, LlmModelTier] = {
    LlmTaskType.EXTRACTION: LlmModelTier.CHEAP,
    LlmTaskType.MATCHING: LlmModelTier.CHEAP,
    LlmTaskType.PARSING: LlmModelTier.CHEAP,
    LlmTaskType.RESUME_WRITING: LlmModelTier.STRONG,
    LlmTaskType.COVER_LETTER_WRITING: LlmModelTier.STRONG,
}


#: How much output each task type needs room for, in tokens. Alongside the tier
#: map because it is the same kind of decision — a property of the task, decided
#: once, rather than something each call site guesses.
#:
#: These exist because one global ceiling cannot fit every task. A two-page
#: résumé parsed into JSON runs to several thousand tokens, while a fit rationale
#: is a paragraph; a limit generous enough for the first is waste on the second,
#: and a limit sized for the second truncates the first. Truncation is the
#: expensive failure: a cut-off JSON object is not partially useful, it is
#: unparseable, and the whole call is billed and wasted.
#:
#: Ceilings, not targets — a task that finishes sooner costs only what it used.
TASK_TYPE_MAX_TOKENS: dict[LlmTaskType, int] = {
    # A job description's requirements: bounded, but lists can be long.
    LlmTaskType.EXTRACTION: 4096,
    # A rationale or a short list of questions.
    LlmTaskType.MATCHING: 2048,
    # A whole résumé restated as JSON — every job, every bullet, every skill.
    # The largest structured output in the app.
    LlmTaskType.PARSING: 8192,
    # A full tailored résumé.
    LlmTaskType.RESUME_WRITING: 8192,
    LlmTaskType.COVER_LETTER_WRITING: 4096,
}


class LlmClientPort(ABC):
    """Sends a prompt to an LLM and returns its text completion."""

    @abstractmethod
    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        """Return the model's text completion for `prompt`.

        `task_type` tells the implementation which model tier to route
        this call to (see `LlmTaskType`). `system` optionally sets the
        system prompt. Raises
        `src.application.exceptions.ExternalServiceError` if the call fails.
        """
