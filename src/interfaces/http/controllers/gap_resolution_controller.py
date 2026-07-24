"""Gap-resolution HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/LLM access, no domain entity manipulation.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.gap_resolution_dtos import (
    GenerateGapResolutionQuestionsInput,
    ResolveGapAnswerInput,
)
from src.application.exceptions import ExternalServiceError
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)
from src.application.use_cases.resolve_gap_answer import ResolveGapAnswer
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_gap_resolution_questions_use_case,
    get_resolve_gap_answer_use_case,
)
from src.interfaces.http.schemas import (
    GapResolutionQuestionResponse,
    GenerateGapQuestionsRequest,
    ResolveGapAnswerRequest,
    ResolveGapAnswerResponse,
)

router = APIRouter(
    prefix="/api/gap-resolution",
    tags=["gap-resolution"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/questions", response_model=list[GapResolutionQuestionResponse])
async def generate_gap_resolution_questions(
    body: GenerateGapQuestionsRequest,
    use_case: GenerateGapResolutionQuestions = Depends(
        get_generate_gap_resolution_questions_use_case
    ),
) -> list[GapResolutionQuestionResponse]:
    try:
        outputs = await use_case.execute(
            GenerateGapResolutionQuestionsInput(gaps=body.gaps)
        )
    except ExternalServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [GapResolutionQuestionResponse(**asdict(output)) for output in outputs]


@router.post("/answers", response_model=ResolveGapAnswerResponse)
async def resolve_gap_answer(
    body: ResolveGapAnswerRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ResolveGapAnswer = Depends(get_resolve_gap_answer_use_case),
) -> ResolveGapAnswerResponse:
    try:
        output = await use_case.execute(
            ResolveGapAnswerInput(
                user_id=user.subject,
                gap=body.gap,
                question_text=body.question,
                answer_text=body.answer,
            )
        )
    except ExternalServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return ResolveGapAnswerResponse(**asdict(output))
