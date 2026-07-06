import pytest

from src.domain.entities.job_application import JobApplication
from src.domain.exceptions import BusinessRuleViolation, InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.match_score import MatchScore


def _app() -> JobApplication:
    return JobApplication(
        id="app-1",
        candidate_email=EmailAddress("jane@example.com"),
        company_name="Acme",
        role_title="Engineer",
        job_description="Build things.",
    )


def test_new_application_starts_as_draft():
    assert _app().status is ApplicationStatus.DRAFT


def test_submit_moves_to_applied():
    app = _app()
    app.submit()
    assert app.status is ApplicationStatus.APPLIED


def test_invalid_status_transition_raises():
    app = _app()
    app.submit()  # APPLIED
    with pytest.raises(BusinessRuleViolation):
        app.change_status(ApplicationStatus.OFFER)  # not allowed from APPLIED


def test_empty_company_name_rejected():
    with pytest.raises(InvalidValueError):
        JobApplication(
            id="x",
            candidate_email=EmailAddress("a@b.com"),
            company_name="  ",
            role_title="Dev",
            job_description="desc",
        )


def test_attach_analysis_sets_score_and_letter():
    app = _app()
    app.attach_analysis(MatchScore(88), "Dear hiring manager...")
    assert int(app.match_score) == 88
    assert app.match_score.is_strong_match
    assert app.tailored_cover_letter is not None
