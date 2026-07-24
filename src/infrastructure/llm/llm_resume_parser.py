"""LLM implementation of the ResumeParserPort.

Wraps a routed call through `LlmClientPort` behind the clean port
interface defined in the application layer — the use case never knows
Anthropic (or any other provider) exists. The call always uses
`LlmTaskType.PARSING`, which `TASK_TYPE_TIERS` routes to the cheap model
tier (see `src/application/ports/llm_client_port.py`).

The model is instructed to return `null` for anything it can't find in
the resume text rather than guess, and this adapter mirrors that
discipline on the way back out: any field or list entry that's missing,
malformed, or the wrong type is dropped rather than defaulted, so a messy
resume (or an occasionally sloppy model response) degrades gracefully
instead of fabricating data or crashing the request.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.application.ports.resume_parser_port import (
    ParsedEducationEntry,
    ParsedResumeData,
    ParsedSkill,
    ParsedWorkHistoryEntry,
    ResumeParserPort,
)
from src.domain.value_objects.proficiency_level import ProficiencyLevel

_SYSTEM_PROMPT = """You are a precise resume-parsing assistant.

Extract structured facts from the candidate's resume text and return
ONLY a single JSON object — no markdown code fences, no commentary —
matching exactly this shape:

{
  "full_name": string or null,
  "email": string or null,
  "phone": string or null,
  "headline": string or null,
  "location": string or null,
  "work_history": [
    {
      "company_name": string or null,
      "job_title": string or null,
      "start_date": "YYYY-MM-DD" or null,
      "end_date": "YYYY-MM-DD" or null,
      "location": string or null,
      "description": string or null
    }
  ],
  "education": [
    {
      "institution_name": string or null,
      "degree": string or null,
      "field_of_study": string or null,
      "start_date": "YYYY-MM-DD" or null,
      "end_date": "YYYY-MM-DD" or null,
      "description": string or null
    }
  ],
  "skills": [
    {
      "name": string or null,
      "proficiency": one of "beginner", "intermediate", "advanced", \
"expert", or null,
      "years_of_experience": integer or null
    }
  ]
}

Rules:
- Never invent or guess a value. If the resume does not state it, use
  null for that field (or omit the entry entirely if nothing useful was
  found for it).
- If only a month/year is known for a date, use the first of the month
  ("YYYY-MM-01").
- If a job or program is still ongoing, set its "end_date" to null.
- Return ONLY the JSON object described above.
"""


class LlmResumeParser(ResumeParserPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def parse(self, resume_text: str) -> ParsedResumeData:
        raw = await self._llm_client.complete(
            resume_text, task_type=LlmTaskType.PARSING, system=_SYSTEM_PROMPT
        )
        payload = self._decode(raw)

        return ParsedResumeData(
            full_name=_as_str(payload.get("full_name")),
            email=_as_str(payload.get("email")),
            phone=_as_str(payload.get("phone")),
            headline=_as_str(payload.get("headline")),
            location=_as_str(payload.get("location")),
            work_history=[
                _parse_work_history(item)
                for item in _as_list(payload.get("work_history"))
            ],
            education=[
                _parse_education(item) for item in _as_list(payload.get("education"))
            ],
            skills=[_parse_skill(item) for item in _as_list(payload.get("skills"))],
        )

    @staticmethod
    def _decode(raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                f"Resume parsing returned invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "Resume parsing returned JSON that wasn't an object."
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


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _as_proficiency(value: Any) -> ProficiencyLevel | None:
    if not isinstance(value, str):
        return None
    try:
        return ProficiencyLevel(value.strip().lower())
    except ValueError:
        return None


def _as_years(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _parse_work_history(item: dict[str, Any]) -> ParsedWorkHistoryEntry:
    return ParsedWorkHistoryEntry(
        company_name=_as_str(item.get("company_name")),
        job_title=_as_str(item.get("job_title")),
        start_date=_as_date(item.get("start_date")),
        end_date=_as_date(item.get("end_date")),
        location=_as_str(item.get("location")),
        description=_as_str(item.get("description")),
    )


def _parse_education(item: dict[str, Any]) -> ParsedEducationEntry:
    return ParsedEducationEntry(
        institution_name=_as_str(item.get("institution_name")),
        degree=_as_str(item.get("degree")),
        field_of_study=_as_str(item.get("field_of_study")),
        start_date=_as_date(item.get("start_date")),
        end_date=_as_date(item.get("end_date")),
        description=_as_str(item.get("description")),
    )


def _parse_skill(item: dict[str, Any]) -> ParsedSkill:
    return ParsedSkill(
        name=_as_str(item.get("name")),
        proficiency=_as_proficiency(item.get("proficiency")),
        years_of_experience=_as_years(item.get("years_of_experience")),
    )
