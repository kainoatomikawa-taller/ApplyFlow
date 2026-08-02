"""The tracker feeding back into matching, checked across the epics it spans.

The unit tests elsewhere check each piece against a hand-built fixture:
`AppliedJobIndex` against postings, `RankMatchedJobPostings` against a stubbed
tracker. What they cannot check is that the pieces agree with the code they
have to line up with — Epic 02's ingestion dedup on one side, Epic 06's
submission logging on the other. That is what this file is for, and it is why
these tests drive the *real* `IngestAggregatorJobs` and the *real*
`SubmittedApplicationLog` rather than constructing the rows they would have
written:

- **Against Epic 02 (acceptance criterion 4).** Ingestion decides what counts
  as the same listing. If canonical identity ever disagreed with that rule,
  a candidate would be nudged to re-apply to a posting the ingest layer had
  already called a duplicate of one they applied to. So the postings here come
  out of `IngestAggregatorJobs`, dedup key and all, not out of a `JobPosting(...)`
  literal written to match.
- **Against Epic 06.** Suppression reads what submission logging wrote. A test
  that built the tracked row by hand could keep passing while the two ends
  drifted on which company/title/location string actually lands in the table.

No database and no network: every port is a fake, per this layer's convention.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.dtos.job_ingestion_dtos import IngestAggregatorJobsInput
from src.application.dtos.ranked_job_dtos import RankMatchedJobsInput
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.job_aggregator_port import (
    AggregatorJobListing,
    AggregatorPage,
    JobAggregatorPort,
)
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.application.use_cases.ingest_aggregator_jobs import IngestAggregatorJobs
from src.application.use_cases.rank_matched_job_postings import RankMatchedJobPostings
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.user_profile import UserProfile
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    InMemoryTrackedApplicationRepository,
    SequentialIdGenerator,
)

_USER_ID = "user-1"
_AS_OF = date(2026, 1, 1)
_APPLIED_AT = datetime(2026, 3, 1, tzinfo=UTC)


# ---- fakes ------------------------------------------------------------------


class FakeIdGenerator(IdGeneratorPort):
    def __init__(self, prefix: str = "job") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n}"


class FakeJobAggregator(JobAggregatorPort):
    def __init__(self, listings: list[AggregatorJobListing], source: str) -> None:
        self._listings = listings
        self._source = source

    @property
    def source_name(self) -> str:
        return self._source

    async def fetch_page(
        self, *, keywords: str, location: str | None, page: int
    ) -> AggregatorPage:
        if page > 1:
            return AggregatorPage(listings=[], has_more=False)
        return AggregatorPage(listings=self._listings, has_more=False)


class FakeJobPostingRepository(JobPostingRepository):
    """Implements `find_duplicate` with Epic 02's real key — (source,
    normalized company/title/location) — because that key is precisely what
    these tests are checking canonical identity against."""

    def __init__(self) -> None:
        self.saved: list[JobPosting] = []

    async def add(self, job_posting: JobPosting) -> None:
        self.saved.append(job_posting)

    async def update(self, job_posting: JobPosting) -> None:
        for index, existing in enumerate(self.saved):
            if existing.id == job_posting.id:
                self.saved[index] = job_posting
                return

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((j for j in self.saved if j.id == job_posting_id), None)

    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        return next(
            (
                j
                for j in self.saved
                if j.source == source
                and j.normalized_company == normalized_company
                and j.normalized_title == normalized_title
                and j.normalized_location == normalized_location
            ),
            None,
        )

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        cutoff = as_of - timedelta(days=recheck_after_days)
        due = [
            j
            for j in self.saved
            if j.is_active
            and (j.last_checked_at is None or j.last_checked_at <= cutoff)
        ]
        return due[:batch_size]

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [j for j in self.saved if j.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [j for j in self.saved if j.requirements is None][:limit]


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


class FakeRationaleGenerator(JobFitRationaleGeneratorPort):
    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        matched: tuple[str, ...],
        gaps: tuple[str, ...],
    ) -> str:
        return "Good fit."


# ---- helpers ----------------------------------------------------------------


def _listing(**overrides: object) -> AggregatorJobListing:
    defaults: dict[str, object] = {
        "external_id": "1",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://jobs.example.com/1",
        "description": "Build things.",
        "location": "New York, NY",
    }
    defaults.update(overrides)
    return AggregatorJobListing(**defaults)


async def _ingest(
    postings: FakeJobPostingRepository,
    listings: list[AggregatorJobListing],
    *,
    source: str = "adzuna",
    id_prefix: str = "job",
) -> int:
    """Run Epic 02's real ingestion and report how many rows it skipped as
    duplicates."""
    use_case = IngestAggregatorJobs(
        repository=postings,
        aggregator=FakeJobAggregator(listings, source=source),
        id_generator=FakeIdGenerator(prefix=id_prefix),
    )
    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="backend", location=None, max_pages=1)
    )
    return result.skipped_duplicate_count


async def _log_application(
    *,
    postings: FakeJobPostingRepository,
    applications: InMemoryTrackedApplicationRepository,
    job_posting_id: str,
) -> None:
    """Run Epic 06's real submission logging against a stored resume snapshot,
    so the tracked row is written by the code that writes it in production."""
    documents = InMemoryApplicationDocumentRepository()
    await documents.add(
        ApplicationDocument(
            id="doc-resume",
            user_id=_USER_ID,
            job_posting_id=job_posting_id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
            content="EXPERIENCE\nBackend Engineer at Acme",
            version=1,
            backing_sources=(ProvenanceSource.PARSED_RESUME,),
        )
    )
    log = SubmittedApplicationLog(
        tracked_application_repository=applications,
        document_repository=documents,
        job_posting_repository=postings,
        id_generator=SequentialIdGenerator(prefix="tracked"),
    )
    await log.record(
        user_id=_USER_ID,
        job_posting_id=job_posting_id,
        submission_key=f"review-for-{job_posting_id}",
        applied_at=_APPLIED_AT,
    )


def _ranker(
    postings: FakeJobPostingRepository,
    applications: InMemoryTrackedApplicationRepository,
) -> RankMatchedJobPostings:
    profile = UserProfile(
        id="profile-1",
        user_id=_USER_ID,
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    return RankMatchedJobPostings(
        job_posting_repository=postings,
        profile_repository=FakeProfileRepository([profile]),
        rationale_generator=FakeRationaleGenerator(),
        tracked_application_repository=applications,
    )


async def _matched_ids(ranker: RankMatchedJobPostings) -> list[str]:
    result = await ranker.execute(RankMatchedJobsInput(user_id=_USER_ID, as_of=_AS_OF))
    return [entry.job_posting.id for entry in result]


# ---- the flow ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_job_applied_to_through_the_real_log_stops_being_matched():
    """Ingest → apply → re-match. The end-to-end claim of the ticket."""
    postings = FakeJobPostingRepository()
    applications = InMemoryTrackedApplicationRepository()
    await _ingest(
        postings,
        [_listing(external_id="1"), _listing(external_id="2", company="Globex")],
    )
    ranker = _ranker(postings, applications)

    assert await _matched_ids(ranker) == ["job-1", "job-2"]

    await _log_application(
        postings=postings, applications=applications, job_posting_id="job-1"
    )

    assert await _matched_ids(ranker) == ["job-2"]


@pytest.mark.asyncio
async def test_the_same_role_re_ingested_from_another_source_is_still_suppressed():
    """Acceptance criterion 4, the case that separates identity from ids.

    Epic 02's dedup key is per source, so the same opening arriving from a
    second aggregator is legitimately a *new row* with a *new id* — it is not
    a duplicate by that rule. The candidate has still applied to the role, and
    matching has to know that.
    """
    postings = FakeJobPostingRepository()
    applications = InMemoryTrackedApplicationRepository()
    await _ingest(postings, [_listing()], source="adzuna", id_prefix="adzuna-job")
    await _log_application(
        postings=postings, applications=applications, job_posting_id="adzuna-job-1"
    )

    skipped = await _ingest(
        postings,
        [_listing(company="  ACME   CORP ", title="backend  engineer")],
        source="greenhouse",
        id_prefix="greenhouse-job",
    )

    # Epic 02 kept it: a different source is a different dedup key.
    assert skipped == 0
    assert {posting.id for posting in postings.saved} == {
        "adzuna-job-1",
        "greenhouse-job-1",
    }
    # Matching drops it anyway: same role, already applied to.
    assert await _matched_ids(_ranker(postings, applications)) == []


@pytest.mark.asyncio
async def test_identity_and_the_dedup_key_agree_on_what_one_listing_is():
    """Where Epic 02 *does* collapse two listings, so does suppression. If
    these two rules ever diverged, one of the pair would come back as a job to
    apply to after the other had been applied to."""
    postings = FakeJobPostingRepository()
    applications = InMemoryTrackedApplicationRepository()

    await _ingest(postings, [_listing()])
    skipped = await _ingest(
        postings,
        [_listing(external_id="2", company="acme corp ", title="Backend  Engineer")],
    )

    assert skipped == 1
    assert len(postings.saved) == 1

    await _log_application(
        postings=postings, applications=applications, job_posting_id="job-1"
    )
    assert await _matched_ids(_ranker(postings, applications)) == []


@pytest.mark.asyncio
async def test_applying_to_one_city_does_not_hide_the_same_role_in_another():
    """Location is in both rules. Epic 02 keeps the two postings apart, and so
    does suppression — the candidate has not applied to the Berlin opening."""
    postings = FakeJobPostingRepository()
    applications = InMemoryTrackedApplicationRepository()
    skipped = await _ingest(
        postings,
        [
            _listing(external_id="1", location="New York, NY"),
            _listing(external_id="2", location="Berlin, DE"),
        ],
    )
    assert skipped == 0

    await _log_application(
        postings=postings, applications=applications, job_posting_id="job-1"
    )

    assert await _matched_ids(_ranker(postings, applications)) == ["job-2"]
