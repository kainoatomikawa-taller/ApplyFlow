"""Job-match-feedback HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB access, no domain entity manipulation.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.job_match_feedback_dtos import SubmitJobMatchFeedbackInput
from src.application.use_cases.analyze_scoring_feedback import (
    AnalyzeScoringFeedback,
)
from src.application.use_cases.list_job_match_feedback import (
    ListJobMatchFeedback,
)
from src.application.use_cases.submit_job_match_feedback import (
    SubmitJobMatchFeedback,
)
from src.domain.exceptions import InvalidValueError, JobPostingNotFoundError
from src.interfaces.http.dependencies import (
    get_analyze_scoring_feedback_use_case,
    get_current_user,
    get_list_job_match_feedback_use_case,
    get_submit_job_match_feedback_use_case,
)
from src.interfaces.http.schemas import (
    JobMatchFeedbackResponse,
    ScoringFeedbackSummaryResponse,
    SubmitJobMatchFeedbackRequest,
)

router = APIRouter(
    prefix="/api/job-postings",
    tags=["job-match-feedback"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/{job_posting_id}/feedback",
    response_model=JobMatchFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    job_posting_id: str,
    body: SubmitJobMatchFeedbackRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SubmitJobMatchFeedback = Depends(get_submit_job_match_feedback_use_case),
) -> JobMatchFeedbackResponse:
    try:
        output = await use_case.execute(
            SubmitJobMatchFeedbackInput(
                user_id=user.subject,
                job_posting_id=job_posting_id,
                rating=body.rating,
                score_at_feedback=body.score_at_feedback,
            )
        )
    except JobPostingNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return JobMatchFeedbackResponse(**asdict(output))


@router.get("/feedback", response_model=list[JobMatchFeedbackResponse])
async def list_feedback(
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListJobMatchFeedback = Depends(get_list_job_match_feedback_use_case),
) -> list[JobMatchFeedbackResponse]:
    outputs = await use_case.execute(user.subject, limit=limit)
    return [JobMatchFeedbackResponse(**asdict(o)) for o in outputs]


@router.get("/feedback/analysis", response_model=ScoringFeedbackSummaryResponse)
async def get_scoring_feedback_analysis(
    limit: int = Query(default=1000, ge=1, le=10_000),
    use_case: AnalyzeScoringFeedback = Depends(get_analyze_scoring_feedback_use_case),
) -> ScoringFeedbackSummaryResponse:
    output = await use_case.execute(limit=limit)
    return ScoringFeedbackSummaryResponse(**asdict(output))
