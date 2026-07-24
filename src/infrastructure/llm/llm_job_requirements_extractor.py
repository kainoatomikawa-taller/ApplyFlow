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
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

_SYSTEM_PROMPT = """You are a precise job-description-parsing assistant.

Extract structured requirement attributes from the job posting text and
return ONLY a single JSON object — no markdown code fences, no commentary
— matching exactly this shape:

{
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


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [_as_str(item) for item in value]
    return [item for item in cleaned if item is not None]
