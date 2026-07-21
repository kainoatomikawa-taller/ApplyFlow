"""DTOs — input/output contracts for LLM completion use cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmCompletionInput:
    prompt: str
    system: str | None = None


@dataclass(frozen=True)
class LlmCompletionOutput:
    text: str
