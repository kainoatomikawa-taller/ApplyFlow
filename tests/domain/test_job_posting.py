import pytest

from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError
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
