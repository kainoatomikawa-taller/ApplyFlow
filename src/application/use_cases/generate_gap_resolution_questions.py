"""GenerateGapResolutionQuestions use case — turns a list of unmet-
requirement gaps (see `DetectJobRequirementGaps`) into one neutrally-
phrased question per gap, in the same order, so a caller can walk the
candidate through them one at a time.

Gaps are processed in sequence rather than fanned out concurrently: the
gap-resolution loop this feeds is inherently sequential from the
candidate's point of view (one question at a time), and keeping the
generation order matching the input order is what lets a caller present
question N right after gap N without re-sorting anything.
"""

from __future__ import annotations

from src.application.dtos.gap_resolution_dtos import (
    GapResolutionQuestionOutput,
    GenerateGapResolutionQuestionsInput,
)
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)


class GenerateGapResolutionQuestions:
    def __init__(self, generator: GapResolutionQuestionGeneratorPort) -> None:
        self._generator = generator

    async def execute(
        self, dto: GenerateGapResolutionQuestionsInput
    ) -> list[GapResolutionQuestionOutput]:
        outputs: list[GapResolutionQuestionOutput] = []
        for gap in dto.gaps:
            question = await self._generator.generate_question(gap=gap)
            outputs.append(GapResolutionQuestionOutput(gap=gap, question=question))
        return outputs
