"""Unit tests for AppliedJobIndex — the roles a candidate has already applied
to, tested against postings the matching layer would otherwise surface.

The cases worth having are the ones where the posting is *not* the row the
application was made against: relisted under a new id, re-ingested from
another source, retitled with different spacing. Matching on posting id would
pass a naive test and still nudge the candidate to re-apply.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.services.applied_job_index import AppliedJobIndex
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity

_APPLIED_AT = datetime(2026, 3, 1, tzinfo=UTC)


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Build things.",
        "location": "New York, NY",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def _application(**overrides: object) -> TrackedApplication:
    defaults: dict[str, object] = {
        "id": "tracked-1",
        "user_id": "user-1",
        "job_posting_id": "job-1",
        "submission_key": "review-1",
        "company_name": "Acme Corp",
        "role_title": "Backend Engineer",
        "job_location": "New York, NY",
        "applied_at": _APPLIED_AT,
        "resume_document_id": "doc-resume",
    }
    defaults.update(overrides)
    return TrackedApplication(**defaults)


def test_a_posting_the_candidate_applied_to_is_recognized():
    index = AppliedJobIndex.from_applications([_application()])

    assert index.has_applied_to(_posting()) is True


def test_an_unapplied_posting_is_not():
    index = AppliedJobIndex.from_applications([_application()])

    assert index.has_applied_to(_posting(id="job-2", company="Globex")) is False


def test_an_empty_index_suppresses_nothing():
    assert AppliedJobIndex().has_applied_to(_posting()) is False
    assert AppliedJobIndex.from_applications([]).has_applied_to(_posting()) is False


def test_the_same_role_relisted_under_a_new_id_still_counts_as_applied():
    """The reason this matches on identity rather than `job_posting_id`: an
    employer relisting the role produces a row the candidate never applied
    to, for a job they did."""
    index = AppliedJobIndex.from_applications([_application(job_posting_id="job-1")])

    assert index.has_applied_to(_posting(id="job-999")) is True


def test_the_same_role_from_another_aggregator_still_counts_as_applied():
    index = AppliedJobIndex.from_applications([_application()])

    relisted = _posting(id="job-2", source="greenhouse")
    assert index.has_applied_to(relisted) is True


def test_casing_and_spacing_differences_do_not_reopen_a_nudge():
    index = AppliedJobIndex.from_applications(
        [_application(company_name="ACME  CORP", role_title="backend engineer")]
    )

    assert index.has_applied_to(_posting()) is True


def test_the_same_title_in_another_city_is_a_job_the_candidate_has_not_applied_to():
    index = AppliedJobIndex.from_applications(
        [_application(job_location="New York, NY")]
    )

    assert index.has_applied_to(_posting(id="job-2", location="Berlin, DE")) is False


def test_a_role_at_another_company_is_not_suppressed():
    index = AppliedJobIndex.from_applications([_application(company_name="Acme Corp")])

    assert index.has_applied_to(_posting(id="job-2", company="Globex")) is False


def test_a_rejected_application_still_suppresses_the_nudge():
    """Status is deliberately not consulted — a rejection is the strongest
    reason not to suggest applying again."""
    index = AppliedJobIndex.from_applications(
        [_application(status=ApplicationStatus.REJECTED)]
    )

    assert index.has_applied_to(_posting()) is True


def test_a_withdrawn_application_still_suppresses_the_nudge():
    index = AppliedJobIndex.from_applications(
        [_application(status=ApplicationStatus.WITHDRAWN)]
    )

    assert index.has_applied_to(_posting()) is True


def test_only_the_named_candidates_applications_are_indexed():
    """The index holds whatever it is given — scoping to one candidate is the
    caller's query, and this asserts the index does not silently widen it."""
    index = AppliedJobIndex.from_applications([_application(company_name="Globex")])

    assert index.has_applied_to(_posting()) is False


def test_applying_to_one_role_twice_is_one_identity():
    index = AppliedJobIndex.from_applications(
        [
            _application(id="tracked-1", submission_key="review-1"),
            _application(id="tracked-2", submission_key="review-2"),
        ]
    )

    assert len(index) == 1


def test_it_can_be_built_from_identities_directly():
    index = AppliedJobIndex(
        [
            CanonicalJobIdentity.of(
                company="Acme Corp", title="Backend Engineer", location="New York, NY"
            )
        ]
    )

    assert index.has_applied_to(_posting()) is True
