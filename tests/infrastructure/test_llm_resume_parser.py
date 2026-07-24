"""Tests for LlmResumeParser — the LLM implementation of ResumeParserPort.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline and deterministically while proving the routing
contract (task_type=PARSING -> cheap tier, enforced upstream by
`TASK_TYPE_TIERS`) and the "never fabricate" parsing discipline.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.infrastructure.llm.llm_resume_parser import LlmResumeParser


class FakeLlmClient(LlmClientPort):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, LlmTaskType, str | None]] = []

    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        self.calls.append((prompt, task_type, system))
        return self.response


@pytest.mark.asyncio
async def test_parse_routes_through_the_cheap_parsing_task_type():
    client = FakeLlmClient(json.dumps({}))
    parser = LlmResumeParser(client)

    await parser.parse("resume text")

    assert client.calls[0][0] == "resume text"
    assert client.calls[0][1] == LlmTaskType.PARSING


@pytest.mark.asyncio
async def test_parse_extracts_full_structured_payload():
    payload = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-1234",
        "headline": "Senior Engineer",
        "location": "Remote",
        "work_history": [
            {
                "company_name": "Acme",
                "job_title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": None,
                "location": "NYC",
                "description": "Built things.",
            }
        ],
        "education": [
            {
                "institution_name": "State University",
                "degree": "B.S. Computer Science",
                "field_of_study": "CS",
                "start_date": "2016-09-01",
                "end_date": "2020-05-01",
                "description": None,
            }
        ],
        "skills": [
            {"name": "Python", "proficiency": "expert", "years_of_experience": 8}
        ],
    }
    client = FakeLlmClient(json.dumps(payload))
    parser = LlmResumeParser(client)

    result = await parser.parse("resume text")

    assert result.full_name == "Jane Doe"
    assert result.email == "jane@example.com"
    assert result.work_history[0].start_date == date(2020, 1, 1)
    assert result.work_history[0].end_date is None
    assert result.education[0].institution_name == "State University"
    assert result.skills[0].proficiency == ProficiencyLevel.EXPERT
    assert result.skills[0].years_of_experience == 8


@pytest.mark.asyncio
async def test_parse_strips_markdown_code_fences():
    fenced = "```json\n" + json.dumps({"full_name": "Jane Doe"}) + "\n```"
    client = FakeLlmClient(fenced)
    parser = LlmResumeParser(client)

    result = await parser.parse("resume text")

    assert result.full_name == "Jane Doe"


@pytest.mark.asyncio
async def test_parse_raises_external_service_error_on_invalid_json():
    client = FakeLlmClient("not json at all")
    parser = LlmResumeParser(client)

    with pytest.raises(ExternalServiceError, match="invalid JSON"):
        await parser.parse("resume text")


@pytest.mark.asyncio
async def test_parse_raises_external_service_error_when_payload_is_not_an_object():
    client = FakeLlmClient(json.dumps([1, 2, 3]))
    parser = LlmResumeParser(client)

    with pytest.raises(ExternalServiceError, match="wasn't an object"):
        await parser.parse("resume text")


@pytest.mark.asyncio
async def test_parse_handles_an_empty_resume_without_fabricating_anything():
    client = FakeLlmClient(json.dumps({}))
    parser = LlmResumeParser(client)

    result = await parser.parse("")

    assert result.full_name is None
    assert result.email is None
    assert result.work_history == []
    assert result.education == []
    assert result.skills == []


@pytest.mark.asyncio
async def test_parse_drops_malformed_entries_instead_of_crashing():
    payload = {
        "full_name": "  ",  # blank -> None
        "work_history": [
            "not a dict",
            {"company_name": "Acme", "start_date": "not-a-date"},
        ],
        "education": None,  # wrong type entirely -> treated as empty
        "skills": [
            {"name": "Rust", "proficiency": "wizard", "years_of_experience": -3},
            {"name": "Go", "years_of_experience": True},
        ],
    }
    client = FakeLlmClient(json.dumps(payload))
    parser = LlmResumeParser(client)

    result = await parser.parse("messy resume")

    assert result.full_name is None
    assert len(result.work_history) == 1
    assert result.work_history[0].company_name == "Acme"
    assert result.work_history[0].start_date is None  # unparseable -> dropped
    assert result.education == []
    assert result.skills[0].proficiency is None  # unknown enum value -> dropped
    assert result.skills[0].years_of_experience is None  # negative -> dropped
    assert result.skills[1].years_of_experience is None  # bool is not an int here
