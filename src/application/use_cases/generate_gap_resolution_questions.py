"""GenerateGapResolutionQuestions use case — turns a list of unmet-
requirement gaps (see `DetectJobRequirementGaps`) into one neutrally-
phrased question per gap, in the same order, so a caller can walk the
candidate through them one at a time — *except* for gaps a previously
remembered answer already covers, which are reported as already answered
instead of being asked again.

That suppression is what makes the answer memory `ResolveGapAnswer` writes
pay off across applications: an answer given once for "Kubernetes
experience" on job A must not be re-asked when job B lists the same
requirement in different words. Matching is semantic, not textual —
equivalently-worded gaps produce equivalently-worded questions, whose
embeddings sit close together in vector space, which is exactly what
`AnswerSimilarityMatcher` (a pure domain service, reused here rather than
re-implemented) is for. Exact string equality would miss every rewording
and re-ask the candidate anyway.

The question is generated *before* the memory lookup rather than after,
because the stored embedding is of the remembered *question* text (see
`AnswerMemory`) — so the comparable key for a new gap is the question that
gap produces, not the raw requirement phrasing, which embeds differently.
The cost is one generation call for a gap that turns out to be already
answered; that buys a match on the same footing the answer was stored on,
and questions are generated on the cheap LLM tier.

Gaps are processed in sequence rather than fanned out concurrently: the
gap-resolution loop this feeds is inherently sequential from the
candidate's point of view (one question at a time), and keeping the output
order matching the input order is what lets a caller present question N
right after gap N without re-sorting anything.
"""

from __future__ import annotations

from src.application.dtos.gap_resolution_dtos import (
    AlreadyAnsweredGapOutput,
    GapResolutionQuestionOutput,
    GapResolutionQuestionsOutput,
    GenerateGapResolutionQuestionsInput,
)
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.services.answer_similarity_matcher import (
    AnswerMatch,
    AnswerSimilarityMatcher,
)


class GenerateGapResolutionQuestions:
    def __init__(
        self,
        generator: GapResolutionQuestionGeneratorPort,
        answer_memory_repository: AnswerMemoryRepository,
        embedding_client: EmbeddingClientPort,
        matcher: AnswerSimilarityMatcher | None = None,
    ) -> None:
        self._generator = generator
        self._answer_memory_repository = answer_memory_repository
        self._embedding_client = embedding_client
        self._matcher = matcher or AnswerSimilarityMatcher()

    async def execute(
        self, dto: GenerateGapResolutionQuestionsInput
    ) -> GapResolutionQuestionsOutput:
        remembered = await self._remembered_answers(dto.user_id, dto.gaps)

        questions: list[GapResolutionQuestionOutput] = []
        already_answered: list[AlreadyAnsweredGapOutput] = []

        for gap in dto.gaps:
            question = await self._generator.generate_question(gap=gap)
            match = await self._find_remembered_answer(
                question, remembered, dto.similarity_threshold
            )
            if match is not None:
                already_answered.append(
                    AlreadyAnsweredGapOutput(
                        gap=gap,
                        answer_memory_id=match.answer_memory.id,
                        similarity_score=match.similarity_score,
                    )
                )
                continue
            questions.append(GapResolutionQuestionOutput(gap=gap, question=question))

        return GapResolutionQuestionsOutput(
            questions=questions, already_answered=already_answered
        )

    async def _remembered_answers(
        self, user_id: str, gaps: list[str]
    ) -> list[AnswerMemory]:
        """Fetch this user's remembered answers once for the whole run,
        and not at all when there is nothing to ask about."""
        if not gaps:
            return []
        return await self._answer_memory_repository.list_by_user_id(user_id)

    async def _find_remembered_answer(
        self,
        question: str,
        remembered: list[AnswerMemory],
        threshold: float | None,
    ) -> AnswerMatch | None:
        """The embedding call is skipped entirely for a candidate with no
        remembered answers — there is nothing for it to match against."""
        if not remembered:
            return None
        question_embedding = await self._embedding_client.embed(question)
        return self._matcher.find_best_match(
            question_embedding, remembered, threshold=threshold
        )
