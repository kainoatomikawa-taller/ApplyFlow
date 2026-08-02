"""Unit tests for CanonicalJobIdentity — what makes two job records the same
role.

The cases that matter are the ones tying this to Epic 02's ingestion dedup.
Two records that dedup considers duplicates must be one identity here, or the
matching layer will nudge a candidate to re-apply to a posting the ingest
layer had already called a duplicate of one they applied to.
"""

from __future__ import annotations

import pytest

from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity


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


def _ingestion_dedup_key(posting: JobPosting) -> tuple[str, str, str, str | None]:
    """The key Epic 02's ingestion passes to
    `JobPostingRepository.find_duplicate`, spelled out here so a change to
    either rule shows up as a failing test rather than as a candidate being
    nudged to re-apply."""
    return (
        posting.source,
        posting.normalized_company,
        posting.normalized_title,
        posting.normalized_location,
    )


# ---- normalization ----------------------------------------------------------


def test_identity_normalizes_case_and_whitespace():
    identity = CanonicalJobIdentity.of(
        company="  Acme   Corp ", title="Senior  Backend Engineer", location="NYC, NY"
    )

    assert identity.company == "acme corp"
    assert identity.title == "senior backend engineer"
    assert identity.location == "nyc, ny"


def test_the_same_role_written_differently_is_one_identity():
    assert CanonicalJobIdentity.of(
        company="ACME CORP", title="Backend  Engineer", location="New York, NY"
    ) == CanonicalJobIdentity.of(
        company="Acme Corp", title="Backend Engineer", location="new york, ny"
    )


def test_identities_are_hashable_so_the_applied_set_is_a_set():
    identities = {
        CanonicalJobIdentity.of(company="Acme", title="Engineer", location="NYC"),
        CanonicalJobIdentity.of(company="acme", title="engineer", location="nyc"),
    }

    assert len(identities) == 1


def test_a_blank_location_is_the_same_as_no_location():
    assert CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location="   "
    ) == CanonicalJobIdentity.of(company="Acme", title="Engineer", location=None)


# ---- what stays distinct ----------------------------------------------------


def test_a_different_location_is_a_different_role():
    assert CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location="New York, NY"
    ) != CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location="Berlin, DE"
    )


def test_no_location_does_not_match_a_located_role():
    """Erring toward showing a job rather than hiding one: a posting naming no
    location is not asserted to be the role the candidate applied to in
    Berlin."""
    assert CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location=None
    ) != CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location="Berlin, DE"
    )


def test_a_nearby_title_is_not_merged():
    """Not fuzzy, on purpose: a matcher loose enough to merge these is loose
    enough to hide a job the candidate never applied to."""
    assert CanonicalJobIdentity.of(
        company="Acme", title="Backend Engineer", location="NYC"
    ) != CanonicalJobIdentity.of(
        company="Acme", title="Backend Engineer II", location="NYC"
    )


def test_the_same_title_at_another_company_is_a_different_role():
    assert CanonicalJobIdentity.of(
        company="Acme", title="Engineer", location="NYC"
    ) != CanonicalJobIdentity.of(company="Globex", title="Engineer", location="NYC")


def test_empty_company_or_title_rejected():
    with pytest.raises(InvalidValueError):
        CanonicalJobIdentity.of(company="   ", title="Engineer")
    with pytest.raises(InvalidValueError):
        CanonicalJobIdentity.of(company="Acme", title="  ")


# ---- agreement with Epic 02's dedup rule ------------------------------------


def test_a_postings_identity_is_built_from_its_epic_02_dedup_fields():
    posting = _posting(company=" Acme  Corp ", title="Backend  Engineer")

    assert posting.canonical_identity == CanonicalJobIdentity(
        company=posting.normalized_company,
        title=posting.normalized_title,
        location=posting.normalized_location,
    )


def test_two_postings_epic_02_would_call_duplicates_share_one_identity():
    """The ingestion dedup key is (source, normalized company/title/location).
    Two listings that collide on it must be one role here."""
    first = _posting(id="job-1", company="Acme Corp", title="Backend Engineer")
    second = _posting(id="job-2", company="  ACME   CORP", title="backend engineer")

    assert _ingestion_dedup_key(first) == _ingestion_dedup_key(second)
    assert first.canonical_identity == second.canonical_identity


def test_identity_ignores_source_where_the_dedup_key_does_not():
    """Epic 02 keeps the same opening from two feeds as two rows — its key is
    per source. Applying through one board still reaches the employer, so this
    identity drops the source."""
    adzuna = _posting(id="job-1", source="adzuna")
    greenhouse = _posting(id="job-2", source="greenhouse")

    assert adzuna.source != greenhouse.source
    assert adzuna.canonical_identity == greenhouse.canonical_identity


def test_a_posting_with_no_location_keeps_a_null_identity_component():
    posting = _posting(location=None)

    assert posting.normalized_location is None
    assert posting.canonical_identity.location is None
