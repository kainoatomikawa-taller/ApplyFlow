"""Job posting HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/LLM access, no domain entity manipulation.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.ranked_job_dtos import RankMatchedJobsInput
from src.application.use_cases.rank_matched_job_postings import (
    RankMatchedJobPostings,
)
from src.domain.exceptions import ProfileNotFoundError
from src.interfaces.http.dependencies import (
    get_current_user,
    get_rank_matched_jobs_use_case,
)
from src.interfaces.http.schemas import RankedJobResponse

router = APIRouter(
    prefix="/api/job-postings",
    tags=["job-postings"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/matches", response_model=list[RankedJobResponse])
async def list_matched_job_postings(
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: RankMatchedJobPostings = Depends(get_rank_matched_jobs_use_case),
) -> list[RankedJobResponse]:
    try:
        outputs = await use_case.execute(
            RankMatchedJobsInput(
                user_id=user.subject, as_of=date.today(), limit=limit
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [RankedJobResponse(**asdict(output)) for output in outputs]
