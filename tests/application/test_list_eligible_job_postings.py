"""Tests for ListEligibleJobPostings — the active job set filtered down to
postings a candidate's profile doesn't fail a hard disqualifier against and
hasn't already been applied to.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.use_cases.list_eligible_job_postings import (
    ListEligibleJobPostings,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from tests.application.conftest import InMemoryTrackedApplicationRepository


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Build things.",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def _profile(**overrides: object) -> UserProfile:
    defaults: dict[str, object] = {
        "id": "profile-1",
        "user_id": "user-1",
        "full_name": "Jane Doe",
        "email": EmailAddress("jane@example.com"),
        "contact_source": ProvenanceSource.USER_ENTERED,
    }
    defaults.update(overrides)
    return UserProfile(**defaults)


class FakeJobPostingRepository(JobPostingRepository):
    def __init__(self, postings: list[JobPosting]) -> None:
        self.postings = postings

    async def add(self, job_posting: JobPosting) -> None:
        self.postings.append(job_posting)

    async def update(self, job_posting: JobPosting) -> None:
        pass

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((p for p in self.postings if p.id == job_posting_id), None)

    async def find_duplicate(self, **kwargs: object) -> JobPosting | None:
        return None

    async def list_due_for_staleness_check(self, **kwargs: object) -> list[JobPosting]:
        return []

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [p for p in self.postings if p.requirements is None][:limit]


class FakeProfileRepository(ProfileRepository):
    def __init__(self, profiles: list[UserProfile]) -> None:
        self.profiles = profiles

    async def add(self, profile: UserProfile) -> None:
        self.profiles.append(profile)

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return next((p for p in self.profiles if p.user_id == user_id), None)

    async def update(self, profile: UserProfile) -> None:
        pass

    async def delete(self, profile_id: str) -> None:
        self.profiles = [p for p in self.profiles if p.id != profile_id]


def _application(**overrides: object) -> TrackedApplication:
    """One record in the candidate's tracker — an application already sent."""
    defaults: dict[str, object] = {
        "id": "tracked-1",
        "user_id": "user-1",
        "job_posting_id": "job-1",
        "submission_key": "review-1",
        "company_name": "Acme Corp",
        "role_title": "Backend Engineer",
        "job_location": None,
        "applied_at": datetime(2026, 3, 1, tzinfo=UTC),
        "resume_document_id": "doc-resume",
    }
    defaults.update(overrides)
    return TrackedApplication(**defaults)


def _use_case(
    postings: list[JobPosting],
    profiles: list[UserProfile],
    applications: list[TrackedApplication] | None = None,
) -> ListEligibleJobPostings:
    return ListEligibleJobPostings(
        job_posting_repository=FakeJobPostingRepository(postings),
        profile_repository=FakeProfileRepository(profiles),
        tracked_application_repository=InMemoryTrackedApplicationRepository(
            applications or []
        ),
    )


@pytest.mark.asyncio
async def test_excludes_a_posting_the_profile_fails_a_hard_disqualifier_on():
    disqualifying = _posting(id="job-citizens-only")
    disqualifying.set_requirements(
        JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    )
    ok = _posting(id="job-open", description="No restrictions.")

    profile = _profile(
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.VISA_HOLDER,
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    use_case = _use_case([disqualifying, ok], [profile])

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-open"]


@pytest.mark.asyncio
async def test_never_excludes_a_posting_over_soft_preferences_alone():
    """Acceptance criterion 4: a near-miss posting — the candidate lacks a
    merely-preferred degree and doesn't meet a soft skill wish-list — must
    still come through, since none of that is a hard disqualifier."""
    near_miss = _posting(id="job-near-miss")
    near_miss.set_requirements(
        JobRequirements(
            degree_level=DegreeLevel.MASTERS,
            degree_required=False,
            remote_type=RemoteType.HYBRID,
            required_skills=("Rust", "Go"),
            min_years_experience=8,
        )
    )
    profile = _profile()
    use_case = _use_case([near_miss], [profile])

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-near-miss"]


@pytest.mark.asyncio
async def test_postings_with_no_extracted_requirements_are_never_excluded():
    posting = _posting(id="job-unprocessed")
    profile = _profile()
    use_case = _use_case([posting], [profile])

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-unprocessed"]


@pytest.mark.asyncio
async def test_raises_when_profile_does_not_exist():
    use_case = _use_case([], [])

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(profile_id="missing-profile")


@pytest.mark.asyncio
async def test_respects_limit_before_filtering():
    postings = [_posting(id=f"job-{i}") for i in range(5)]
    profile = _profile()
    use_case = _use_case(postings, [profile])

    result = await use_case.execute(profile_id="profile-1", limit=2)

    assert len(result) == 2


# ---- already-applied roles (the tracker feeding back into matching) ---------


@pytest.mark.asyncio
async def test_excludes_a_role_the_candidate_already_applied_to():
    applied_to = _posting(id="job-1", company="Acme Corp")
    fresh = _posting(id="job-2", company="Globex")
    use_case = _use_case(
        [applied_to, fresh],
        [_profile()],
        applications=[_application(company_name="Acme Corp")],
    )

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-2"]


@pytest.mark.asyncio
async def test_exclusion_matches_canonical_identity_not_posting_id():
    """The same suppression rule the ranked list uses — a relisted posting is
    a new row for a role the candidate has already applied to."""
    relisted = _posting(id="job-relisted", source="greenhouse", company="ACME  CORP")
    use_case = _use_case(
        [relisted],
        [_profile()],
        applications=[
            _application(job_posting_id="job-long-gone", company_name="Acme Corp")
        ],
    )

    result = await use_case.execute(profile_id="profile-1")

    assert result == []


@pytest.mark.asyncio
async def test_a_role_in_another_location_is_still_eligible():
    berlin = _posting(id="job-berlin", location="Berlin, DE")
    use_case = _use_case(
        [berlin], [_profile()], applications=[_application(job_location="New York, NY")]
    )

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-berlin"]


@pytest.mark.asyncio
async def test_another_candidates_applications_exclude_nothing():
    use_case = _use_case(
        [_posting()], [_profile()], applications=[_application(user_id="user-2")]
    )

    result = await use_case.execute(profile_id="profile-1")

    assert [o.id for o in result] == ["job-1"]


@pytest.mark.asyncio
async def test_already_applied_roles_can_be_asked_for_explicitly():
    use_case = _use_case([_posting()], [_profile()], applications=[_application()])

    result = await use_case.execute(
        profile_id="profile-1", include_already_applied=True
    )

    assert [o.id for o in result] == ["job-1"]
