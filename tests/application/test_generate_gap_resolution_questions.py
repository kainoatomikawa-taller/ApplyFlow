"""Tests for GenerateGapResolutionQuestions — turns a list of gaps into
one neutrally-phrased question per gap, in order.
"""

from __future__ import annotations

import pytest

from src.application.dtos.gap_resolution_dtos import (
    GenerateGapResolutionQuestionsInput,
)
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)


class FakeGenerator(GapResolutionQuestionGeneratorPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_question(self, *, gap: str) -> str:
        self.calls.append(gap)
        return f"Question about: {gap}"


@pytest.mark.asyncio
async def test_generates_one_question_per_gap_in_order():
    generator = FakeGenerator()
    use_case = GenerateGapResolutionQuestions(generator=generator)

    result = await use_case.execute(
        GenerateGapResolutionQuestionsInput(
            gaps=["Kubernetes", "Leadership experience", "5+ years of Python"]
        )
    )

    assert [item.gap for item in result] == [
        "Kubernetes",
        "Leadership experience",
        "5+ years of Python",
    ]
    assert [item.question for item in result] == [
        "Question about: Kubernetes",
        "Question about: Leadership experience",
        "Question about: 5+ years of Python",
    ]
    assert generator.calls == [
        "Kubernetes",
        "Leadership experience",
        "5+ years of Python",
    ]


@pytest.mark.asyncio
async def test_empty_gap_list_yields_no_questions_and_no_calls():
    generator = FakeGenerator()
    use_case = GenerateGapResolutionQuestions(generator=generator)

    result = await use_case.execute(GenerateGapResolutionQuestionsInput(gaps=[]))

    assert result == []
    assert generator.calls == []
