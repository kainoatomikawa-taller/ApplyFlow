from datetime import UTC, date, datetime

import pytest

from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.job_posting_status import JobPostingStatus
from src.domain.value_objects.link_check_outcome import LinkCheckOutcome
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange


def _job_posting(
    *,
    id: str = "job-1",
    source: str = "linkedin",
    company: str = "Acme Corp",
    title: str = "Backend Engineer",
    apply_url: str = "https://jobs.example.com/acme/backend-engineer",
    description: str = "Build things.",
    **kwargs,
) -> JobPosting:
    return JobPosting(
        id=id,
        source=source,
        company=company,
        title=title,
        apply_url=apply_url,
        description=description,
        **kwargs,
    )


def test_valid_job_posting_constructs():
    job_posting = _job_posting()
    assert job_posting.company == "Acme Corp"
    assert job_posting.is_remote is False
    assert job_posting.salary is None


def test_dedup_fields_are_derived_and_normalized():
    job_posting = _job_posting(
        company="  Acme Corp  ", title="Senior  Backend Engineer", location="NYC, NY"
    )
    assert job_posting.normalized_company == "acme corp"
    assert job_posting.normalized_title == "senior backend engineer"
    assert job_posting.normalized_location == "nyc, ny"


def test_no_location_means_no_normalized_location():
    job_posting = _job_posting(location=None)
    assert job_posting.normalized_location is None


def test_empty_id_rejected():
    with pytest.raises(InvalidValueError):
        _job_posting(id="")


def test_empty_company_rejected():
    with pytest.raises(InvalidValueError):
        _job_posting(company="   ")


def test_empty_apply_url_rejected():
    with pytest.raises(InvalidValueError):
        _job_posting(apply_url="")


def test_salary_range_requires_at_least_one_amount():
    with pytest.raises(InvalidValueError):
        SalaryRange(currency="USD", period=SalaryPeriod.YEARLY)


def test_salary_range_rejects_min_greater_than_max():
    with pytest.raises(InvalidValueError):
        SalaryRange(
            currency="USD",
            period=SalaryPeriod.YEARLY,
            min_amount=200_000,
            max_amount=100_000,
        )


def test_salary_range_accepts_a_single_amount():
    salary = SalaryRange(
        currency="USD", period=SalaryPeriod.HOURLY, min_amount=75
    )
    assert salary.max_amount is None


# ---- lifecycle: status defaults ---------------------------------------------


def test_new_job_posting_is_active_with_no_checks_yet():
    job_posting = _job_posting()
    assert job_posting.status == JobPostingStatus.ACTIVE
    assert job_posting.is_active is True
    assert job_posting.last_checked_at is None
    assert job_posting.consecutive_link_failures == 0


def test_negative_consecutive_link_failures_rejected():
    with pytest.raises(InvalidValueError):
        _job_posting(consecutive_link_failures=-1)


# ---- mark_stale_if_expired ---------------------------------------------------


def test_posting_older_than_threshold_is_marked_stale():
    job_posting = _job_posting(posted_at=date(2026, 1, 1))

    job_posting.mark_stale_if_expired(
        as_of=datetime(2026, 3, 1, tzinfo=UTC), stale_after_days=45
    )

    assert job_posting.status == JobPostingStatus.STALE


def test_posting_within_threshold_stays_active():
    job_posting = _job_posting(posted_at=date(2026, 1, 1))

    job_posting.mark_stale_if_expired(
        as_of=datetime(2026, 1, 10, tzinfo=UTC), stale_after_days=45
    )

    assert job_posting.status == JobPostingStatus.ACTIVE


def test_falls_back_to_created_at_when_posted_at_is_missing():
    job_posting = _job_posting(
        posted_at=None, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    job_posting.mark_stale_if_expired(
        as_of=datetime(2026, 3, 1, tzinfo=UTC), stale_after_days=45
    )

    assert job_posting.status == JobPostingStatus.STALE


def test_uses_default_stale_after_days_when_not_given():
    assert JobPosting.DEFAULT_STALE_AFTER_DAYS == 45
    job_posting = _job_posting(posted_at=date(2026, 1, 1))

    # 10 days later: well within the default 45-day threshold.
    job_posting.mark_stale_if_expired(as_of=datetime(2026, 1, 10, tzinfo=UTC))
    assert job_posting.status == JobPostingStatus.ACTIVE

    # 100 days later: past the default 45-day threshold.
    job_posting.mark_stale_if_expired(as_of=datetime(2026, 4, 11, tzinfo=UTC))
    assert job_posting.status == JobPostingStatus.STALE


def test_already_inactive_posting_is_not_reconsidered_by_age():
    job_posting = _job_posting(posted_at=date(2026, 1, 1))
    job_posting.apply_link_check(
        LinkCheckOutcome.CONFIRMED_DEAD, checked_at=datetime(2026, 1, 2, tzinfo=UTC)
    )

    job_posting.mark_stale_if_expired(
        as_of=datetime(2026, 6, 1, tzinfo=UTC), stale_after_days=45
    )

    # Still DEAD_LINK, not overwritten by the (also-true) staleness rule.
    assert job_posting.status == JobPostingStatus.DEAD_LINK


# ---- apply_link_check ---------------------------------------------------------


def test_confirmed_dead_flags_dead_link_on_first_occurrence():
    job_posting = _job_posting()

    job_posting.apply_link_check(
        LinkCheckOutcome.CONFIRMED_DEAD, checked_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert job_posting.status == JobPostingStatus.DEAD_LINK
    assert job_posting.consecutive_link_failures == 1
    assert job_posting.last_checked_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_single_transient_failure_does_not_flag_dead_link():
    job_posting = _job_posting()

    job_posting.apply_link_check(
        LinkCheckOutcome.TRANSIENT_FAILURE,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        dead_link_after_failures=3,
    )

    assert job_posting.status == JobPostingStatus.ACTIVE
    assert job_posting.consecutive_link_failures == 1


def test_transient_failure_flags_dead_link_after_threshold_consecutive_occurrences():
    job_posting = _job_posting()
    checked_at = datetime(2026, 1, 1, tzinfo=UTC)

    for _ in range(2):
        job_posting.apply_link_check(
            LinkCheckOutcome.TRANSIENT_FAILURE,
            checked_at=checked_at,
            dead_link_after_failures=3,
        )
    assert job_posting.status == JobPostingStatus.ACTIVE

    job_posting.apply_link_check(
        LinkCheckOutcome.TRANSIENT_FAILURE,
        checked_at=checked_at,
        dead_link_after_failures=3,
    )
    assert job_posting.status == JobPostingStatus.DEAD_LINK
    assert job_posting.consecutive_link_failures == 3


def test_reachable_resets_the_consecutive_failure_streak():
    job_posting = _job_posting()
    checked_at = datetime(2026, 1, 1, tzinfo=UTC)
    job_posting.apply_link_check(
        LinkCheckOutcome.TRANSIENT_FAILURE,
        checked_at=checked_at,
        dead_link_after_failures=3,
    )
    job_posting.apply_link_check(
        LinkCheckOutcome.TRANSIENT_FAILURE,
        checked_at=checked_at,
        dead_link_after_failures=3,
    )

    job_posting.apply_link_check(LinkCheckOutcome.REACHABLE, checked_at=checked_at)

    assert job_posting.consecutive_link_failures == 0
    assert job_posting.status == JobPostingStatus.ACTIVE


def test_already_dead_link_is_not_reactivated_by_a_later_reachable_check():
    job_posting = _job_posting()
    checked_at = datetime(2026, 1, 1, tzinfo=UTC)
    job_posting.apply_link_check(LinkCheckOutcome.CONFIRMED_DEAD, checked_at=checked_at)

    job_posting.apply_link_check(LinkCheckOutcome.REACHABLE, checked_at=checked_at)

    assert job_posting.status == JobPostingStatus.DEAD_LINK


def test_last_checked_at_updates_even_when_status_does_not_change():
    job_posting = _job_posting()
    checked_at = datetime(2026, 1, 5, tzinfo=UTC)

    job_posting.apply_link_check(LinkCheckOutcome.REACHABLE, checked_at=checked_at)

    assert job_posting.last_checked_at == checked_at


def test_uses_default_dead_link_failure_threshold_when_not_given():
    assert JobPosting.DEFAULT_DEAD_LINK_FAILURE_THRESHOLD == 3
    job_posting = _job_posting()
    checked_at = datetime(2026, 1, 1, tzinfo=UTC)

    for _ in range(2):
        job_posting.apply_link_check(
            LinkCheckOutcome.TRANSIENT_FAILURE, checked_at=checked_at
        )
    assert job_posting.status == JobPostingStatus.ACTIVE

    job_posting.apply_link_check(
        LinkCheckOutcome.TRANSIENT_FAILURE, checked_at=checked_at
    )
    assert job_posting.status == JobPostingStatus.DEAD_LINK
