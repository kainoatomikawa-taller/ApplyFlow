"""LLM implementation of the JobRequirementsExtractorPort.

Wraps a routed call through `LlmClientPort` behind the clean port
interface defined in the application layer — the use case never knows
Anthropic (or any other provider) exists. The call always uses
`LlmTaskType.EXTRACTION`, which `TASK_TYPE_TIERS` routes to the cheap
model tier (see `src/application/ports/llm_client_port.py`).

The model is instructed to return `null`/omit anything it can't find in
the description rather than guess, and this adapter mirrors that
discipline on the way back out: any field or list entry that's missing,
malformed, or the wrong type is dropped rather than defaulted, so a messy
or terse posting (or an occasionally sloppy model response) degrades
gracefully instead of fabricating a requirement or crashing the request.
"""

from __future__ import annotations

import json
from typing import Any

from src.application.exceptions import ExternalServiceError
from src.application.ports.job_requirements_extractor_port import (
    JobRequirementsExtractorPort,
)
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm, TermSeason
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.student_status_requirement import (
    StudentStatusRequirement,
)
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

_SYSTEM_PROMPT = """You are a precise job-description-parsing assistant.

Extract structured requirement attributes from the job posting text and
return ONLY a single JSON object — no markdown code fences, no commentary
— matching exactly this shape:

{
  "employment_type": one of "internship", "co_op", "new_grad", \
"full_time", "part_time", "contract", or null,
  "hiring_term_season": one of "spring", "summer", "fall", "winter", or null,
  "student_status_requirement": one of "current_student", \
"current_undergraduate", "current_graduate_student", "graduated", or null,
  "hiring_term_year": four-digit integer or null,
  "degree_level": one of "high_school", "associate", "bachelors", \
"masters", "doctorate", or null,
  "degree_required": true if the degree is mandatory, false if only \
preferred/nice-to-have, or null if unclear,
  "clearance_level": one of "public_trust", "confidential", "secret", \
"top_secret", "top_secret_sci", or null,
  "clearance_required": true if the clearance is mandatory, false if \
only preferred, or null if unclear,
  "remote_type": one of "on_site", "hybrid", "remote", or null,
  "locations": array of strings naming specific eligible \
locations/constraints (e.g. "United States", "within 4 hours of EST"),
  "work_authorization": one of "citizen", "permanent_resident", \
"visa_holder", "requires_sponsorship", "not_authorized", "other", or null,
  "min_years_experience": integer or null,
  "max_years_experience": integer or null,
  "required_skills": array of strings,
  "preferred_skills": array of strings,
  "preferences": array of strings for any other stated preference that \
doesn't fit the fields above
}

Rules:
- Never invent or guess a value. If the posting does not state an
  attribute, or states it too ambiguously to be sure, use null (or an
  empty array for list fields).
- "employment_type" is what the posting IS, not what it asks for.
  "internship" for a fixed-term student placement; "co_op" only when the
  posting says co-op; "new_grad" for permanent roles explicitly aimed at
  recent graduates ("New Grad", "University Graduate", "Early Career");
  "full_time" for ordinary permanent roles. Do not infer "internship"
  from the word "intern" appearing inside another word — "Internal
  Audit" and "International Tax" are full-time roles.
- "student_status_requirement" is what the posting demands about the
  candidate's *standing*, which is a different question from the degree.
  "must be enrolled in an accredited program" -> "current_student";
  "open to current undergraduates" -> "current_undergraduate"; "must be
  pursuing a PhD or Master's" -> "current_graduate_student"; "must have
  completed your degree before the start date" -> "graduated". Use null
  when the posting says nothing about enrolment — most full-time roles do
  not. A degree requirement on its own is NOT a standing requirement: an
  internship saying "pursuing a Bachelor's" states a degree, and only
  says "current_undergraduate" if it also restricts who may apply.
- "hiring_term_season"/"hiring_term_year" only for a term the posting
  actually names, e.g. "Summer 2027 Internship" -> "summer" + 2027,
  "Intern (Fall 2026)" -> "fall" + 2026. A season with no year stated
  ("Summer Intern") is the season and a null year — do NOT work out which
  year is meant. Leave both null for a role with no academic term.
- "work_authorization" describes the MINIMUM status the employer states
  it will accept (e.g. "requires_sponsorship" if the posting says
  sponsorship is available, "citizen" if it demands U.S. citizenship) —
  not a list of every status mentioned.
- Return ONLY the JSON object described above.
"""


class LlmJobRequirementsExtractor(JobRequirementsExtractorPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def extract(self, description: str) -> JobRequirements:
        raw = await self._llm_client.complete(
            description, task_type=LlmTaskType.EXTRACTION, system=_SYSTEM_PROMPT
        )
        payload = self._decode(raw)

        min_years = _as_nonneg_int(payload.get("min_years_experience"))
        max_years = _as_nonneg_int(payload.get("max_years_experience"))
        if min_years is not None and max_years is not None and min_years > max_years:
            # Can't tell which bound the model got wrong — drop the
            # narrower signal (max) rather than raise or guess.
            max_years = None

        return JobRequirements(
            employment_type=_as_enum(EmploymentType, payload.get("employment_type")),
            student_status_requirement=_as_enum(
                StudentStatusRequirement, payload.get("student_status_requirement")
            ),
            hiring_term=_as_hiring_term(
                payload.get("hiring_term_season"), payload.get("hiring_term_year")
            ),
            degree_level=_as_enum(DegreeLevel, payload.get("degree_level")),
            degree_required=_as_bool(payload.get("degree_required")),
            clearance_level=_as_enum(ClearanceLevel, payload.get("clearance_level")),
            clearance_required=_as_bool(payload.get("clearance_required")),
            remote_type=_as_enum(RemoteType, payload.get("remote_type")),
            locations=tuple(_as_str_list(payload.get("locations"))),
            work_authorization=_as_enum(
                WorkAuthorizationStatus, payload.get("work_authorization")
            ),
            min_years_experience=min_years,
            max_years_experience=max_years,
            required_skills=tuple(_as_str_list(payload.get("required_skills"))),
            preferred_skills=tuple(_as_str_list(payload.get("preferred_skills"))),
            preferences=tuple(_as_str_list(payload.get("preferences"))),
        )

    @staticmethod
    def _decode(raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                f"Job requirements extraction returned invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "Job requirements extraction returned JSON that wasn't an object."
            )
        return payload


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def _as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_nonneg_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _as_enum(enum_cls: type, value: Any) -> Any:
    if not isinstance(value, str):
        return None
    try:
        return enum_cls(value.strip().lower())
    except ValueError:
        return None


def _as_hiring_term(season: Any, year: Any) -> HiringTerm | None:
    """A `HiringTerm` from the two flat fields the prompt asks for, or None.

    Two flat fields rather than a nested object because models answer flat
    schemas more reliably, and the pairing is trivial to reassemble here.

    A year with no season is dropped: "2027" alone does not say which term, and
    `HiringTerm` requires a season. A season with no year is kept, because that is
    the real and common case ("Summer Intern") the value object exists to hold. A
    year outside `HiringTerm`'s range is dropped rather than raised on — a misread
    year should cost the year, not the whole extraction.
    """
    parsed_season = _as_enum(TermSeason, season)
    if parsed_season is None:
        return None
    parsed_year = year if isinstance(year, int) and not isinstance(year, bool) else None
    try:
        return HiringTerm(season=parsed_season, year=parsed_year)
    except InvalidValueError:
        return HiringTerm(season=parsed_season)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [_as_str(item) for item in value]
    return [item for item in cleaned if item is not None]
