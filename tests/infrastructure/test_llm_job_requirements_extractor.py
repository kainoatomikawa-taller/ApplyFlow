"""Tests for LlmJobRequirementsExtractor — the LLM implementation of
JobRequirementsExtractorPort.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline and deterministically while proving the routing
contract (task_type=EXTRACTION -> cheap tier, enforced upstream by
`TASK_TYPE_TIERS`) and the "never fabricate" extraction discipline.
"""

from __future__ import annotations

import json

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.llm.llm_job_requirements_extractor import (
    LlmJobRequirementsExtractor,
)


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
async def test_extract_routes_through_the_cheap_extraction_task_type():
    client = FakeLlmClient(json.dumps({}))
    extractor = LlmJobRequirementsExtractor(client)

    await extractor.extract("job description")

    assert client.calls[0][0] == "job description"
    assert client.calls[0][1] == LlmTaskType.EXTRACTION


@pytest.mark.asyncio
async def test_extract_parses_a_full_structured_payload():
    payload = {
        "degree_level": "bachelors",
        "degree_required": True,
        "clearance_level": "secret",
        "clearance_required": True,
        "remote_type": "hybrid",
        "locations": ["United States"],
        "work_authorization": "requires_sponsorship",
        "min_years_experience": 3,
        "max_years_experience": 6,
        "required_skills": ["Python", "SQL"],
        "preferred_skills": ["Kubernetes"],
        "preferences": ["Startup experience a plus"],
    }
    client = FakeLlmClient(json.dumps(payload))
    extractor = LlmJobRequirementsExtractor(client)

    result = await extractor.extract("job description")

    assert result.degree_level == DegreeLevel.BACHELORS
    assert result.degree_required is True
    assert result.clearance_level == ClearanceLevel.SECRET
    assert result.remote_type == RemoteType.HYBRID
    assert result.locations == ("United States",)
    assert result.work_authorization == WorkAuthorizationStatus.REQUIRES_SPONSORSHIP
    assert result.min_years_experience == 3
    assert result.max_years_experience == 6
    assert result.required_skills == ("Python", "SQL")
    assert result.preferred_skills == ("Kubernetes",)
    assert result.preferences == ("Startup experience a plus",)


@pytest.mark.asyncio
async def test_extract_strips_markdown_code_fences():
    fenced = "```json\n" + json.dumps({"degree_level": "masters"}) + "\n```"
    client = FakeLlmClient(fenced)
    extractor = LlmJobRequirementsExtractor(client)

    result = await extractor.extract("job description")

    assert result.degree_level == DegreeLevel.MASTERS


@pytest.mark.asyncio
async def test_extract_raises_external_service_error_on_invalid_json():
    client = FakeLlmClient("not json at all")
    extractor = LlmJobRequirementsExtractor(client)

    with pytest.raises(ExternalServiceError, match="invalid JSON"):
        await extractor.extract("job description")


@pytest.mark.asyncio
async def test_extract_raises_external_service_error_when_payload_is_not_an_object():
    client = FakeLlmClient(json.dumps([1, 2, 3]))
    extractor = LlmJobRequirementsExtractor(client)

    with pytest.raises(ExternalServiceError, match="wasn't an object"):
        await extractor.extract("job description")


@pytest.mark.asyncio
async def test_extract_handles_a_terse_description_without_fabricating_anything():
    client = FakeLlmClient(json.dumps({}))
    extractor = LlmJobRequirementsExtractor(client)

    result = await extractor.extract("We're hiring.")

    assert result.degree_level is None
    assert result.clearance_level is None
    assert result.remote_type is None
    assert result.locations == ()
    assert result.work_authorization is None
    assert result.min_years_experience is None
    assert result.max_years_experience is None
    assert result.required_skills == ()
    assert result.preferred_skills == ()
    assert result.preferences == ()


@pytest.mark.asyncio
async def test_extract_drops_malformed_entries_instead_of_crashing():
    payload = {
        "degree_level": "phd-ish",  # not a valid enum value -> dropped
        "degree_required": "yes",  # wrong type -> dropped
        "min_years_experience": -3,  # negative -> dropped
        "max_years_experience": True,  # bool is not an int here -> dropped
        "required_skills": ["Python", 42, None, "  "],
        "preferences": "not a list",
    }
    client = FakeLlmClient(json.dumps(payload))
    extractor = LlmJobRequirementsExtractor(client)

    result = await extractor.extract("messy description")

    assert result.degree_level is None
    assert result.degree_required is None
    assert result.min_years_experience is None
    assert result.max_years_experience is None
    assert result.required_skills == ("Python",)
    assert result.preferences == ()


@pytest.mark.asyncio
async def test_extract_drops_max_years_when_it_contradicts_min_years():
    payload = {"min_years_experience": 8, "max_years_experience": 3}
    client = FakeLlmClient(json.dumps(payload))
    extractor = LlmJobRequirementsExtractor(client)

    result = await extractor.extract("job description")

    assert result.min_years_experience == 8
    assert result.max_years_experience is None
