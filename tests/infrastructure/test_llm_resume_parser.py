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


# ---- Contact extras, links, and subject lists --------------------------------
#
# All added when the profile editor gained a résumé-import section: the parser had
# been reading only name/email/phone/headline/location, so links and address never
# reached the profile at all.


@pytest.mark.asyncio
async def test_address_links_and_name_extras_are_read():
    payload = {
        "full_name": "Jane Doe",
        "middle_name": "Quinn",
        "preferred_name": "JD",
        "email": "jane@example.com",
        "street_address": "120 Congress Ave",
        "city": "Austin",
        "state_or_region": "TX",
        "postal_code": "78701",
        "country": "United States",
        "linkedin_url": "https://www.linkedin.com/in/janedoe",
        "github_url": "https://github.com/janedoe",
        "portfolio_url": "https://jane.dev",
    }
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")

    assert result.middle_name == "Quinn"
    assert result.preferred_name == "JD"
    assert result.street_address == "120 Congress Ave"
    assert result.city == "Austin"
    assert result.state_or_region == "TX"
    assert result.postal_code == "78701"
    assert result.country == "United States"
    assert result.linkedin_url == "https://www.linkedin.com/in/janedoe"
    assert result.github_url == "https://github.com/janedoe"
    assert result.portfolio_url == "https://jane.dev"


@pytest.mark.asyncio
async def test_a_bare_host_gains_a_scheme():
    """A résumé header printing "github.com/janedoe" is stating a URL, but
    `ProfileLinks` refuses one with no scheme."""
    payload = {"github_url": "github.com/janedoe"}
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")
    assert result.github_url == "https://github.com/janedoe"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["janedoe", "not a url", "", None, 42])
async def test_a_value_that_is_not_url_shaped_is_dropped(value):
    """Never repaired into a guess: a constructed link points at a stranger's
    profile, which is worse than an empty field."""
    payload = {"linkedin_url": value}
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")
    assert result.linkedin_url is None


@pytest.mark.asyncio
async def test_majors_and_minors_are_read_as_lists():
    payload = {
        "education": [
            {
                "institution_name": "UT Austin",
                "degree": "B.S.",
                "majors": ["Computer Science", "Mathematics"],
                "minors": ["Economics"],
            }
        ]
    }
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")

    entry = result.education[0]
    assert entry.majors == ["Computer Science", "Mathematics"]
    assert entry.minors == ["Economics"]


@pytest.mark.asyncio
async def test_a_bare_string_where_a_subject_list_was_asked_for_is_accepted():
    """The model has still named the subject; dropping it over the container type
    would lose real information."""
    payload = {
        "education": [
            {"institution_name": "UT", "degree": "B.S.", "majors": "Mathematics"}
        ]
    }
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")
    assert result.education[0].majors == ["Mathematics"]


@pytest.mark.asyncio
async def test_junk_inside_a_subject_list_is_skipped_not_fatal():
    payload = {
        "education": [
            {
                "institution_name": "UT",
                "degree": "B.S.",
                "majors": ["Mathematics", None, 7, "  ", {"a": 1}, "Physics"],
            }
        ]
    }
    result = await LlmResumeParser(FakeLlmClient(json.dumps(payload))).parse("text")
    assert result.education[0].majors == ["Mathematics", "Physics"]
