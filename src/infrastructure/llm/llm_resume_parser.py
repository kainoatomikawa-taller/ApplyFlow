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
  "middle_name": string or null,
  "preferred_name": string or null,
  "email": string or null,
  "phone": string or null,
  "headline": string or null,
  "location": string or null,
  "street_address": string or null,
  "city": string or null,
  "state_or_region": string or null,
  "postal_code": string or null,
  "country": string or null,
  "linkedin_url": string or null,
  "github_url": string or null,
  "portfolio_url": string or null,
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
      "majors": [string],
      "minors": [string],
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
- "middle_name" only when the resume actually spells one out. Do not
  turn a middle initial into a name.
- "preferred_name" only when the resume gives one in addition to the
  legal name, e.g. "Michael (Mike) Chen" -> "Mike". Never shorten a name
  yourself.
- Split the location into "city"/"state_or_region"/"country" when the
  resume gives it that way, and also copy it verbatim into "location".
  Leave "street_address" and "postal_code" null unless a full postal
  address is printed — most resumes give only a city.
- URLs must be complete and start with "http://" or "https://". Add the
  scheme to a bare host like "linkedin.com/in/someone", but do not
  otherwise construct a URL from a username.
- "majors" and "minors" are lists. Put a single field of study in
  "majors" as a one-item list, both subjects of a double major in
  "majors", and only a subject the resume explicitly calls a minor in
  "minors". Use [] when the resume does not say.
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
            middle_name=_as_str(payload.get("middle_name")),
            preferred_name=_as_str(payload.get("preferred_name")),
            email=_as_str(payload.get("email")),
            phone=_as_str(payload.get("phone")),
            headline=_as_str(payload.get("headline")),
            location=_as_str(payload.get("location")),
            street_address=_as_str(payload.get("street_address")),
            city=_as_str(payload.get("city")),
            state_or_region=_as_str(payload.get("state_or_region")),
            postal_code=_as_str(payload.get("postal_code")),
            country=_as_str(payload.get("country")),
            linkedin_url=_as_url(payload.get("linkedin_url")),
            github_url=_as_url(payload.get("github_url")),
            portfolio_url=_as_url(payload.get("portfolio_url")),
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


def _as_str_list(value: Any) -> list[str]:
    """A list of non-empty strings, ignoring anything else in it.

    Tolerates a bare string where a list was asked for — a model answering
    "majors": "Mathematics" has still told us the subject, and dropping it over
    the container type would lose real information.
    """
    if isinstance(value, str):
        single = _as_str(value)
        return [single] if single else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _as_str(item)) is not None]


def _as_url(value: Any) -> str | None:
    """A URL the domain's `ProfileLinks` will accept, or None.

    Adds the scheme to a bare host, because a resume header printing
    "github.com/someone" is stating a URL even though it is not spelled as one,
    and `ProfileLinks` refuses anything without a scheme. Anything still not
    URL-shaped is dropped rather than repaired further: a guessed link points at
    a stranger's profile, which is worse than an empty field.
    """
    text = _as_str(value)
    if text is None:
        return None
    if text.startswith(("http://", "https://")):
        return text
    if "." not in text or " " in text:
        return None
    return f"https://{text}"


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
        majors=_as_str_list(item.get("majors")),
        minors=_as_str_list(item.get("minors")),
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
