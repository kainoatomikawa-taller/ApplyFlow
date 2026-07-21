"""DTOs — input/output contracts for LLM completion use cases."""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.llm_client_port import LlmTaskType


@dataclass(frozen=True)
class LlmCompletionInput:
    prompt: str
    task_type: LlmTaskType
    system: str | None = None


@dataclass(frozen=True)
class LlmCompletionOutput:
    text: str
