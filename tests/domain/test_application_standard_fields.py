import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

# ---- ProfileLinks -----------------------------------------------------------


def test_profile_links_defaults_to_all_none():
    links = ProfileLinks()
    assert links.portfolio_url is None
    assert links.linkedin_url is None
    assert links.github_url is None


def test_profile_links_accepts_valid_urls():
    links = ProfileLinks(
        portfolio_url="https://jane.dev",
        linkedin_url="https://www.linkedin.com/in/janedoe",
        github_url="https://github.com/janedoe",
    )
    assert links.github_url == "https://github.com/janedoe"


@pytest.mark.parametrize("bad", ["not-a-url", "ftp://x", "javascript:alert(1)"])
def test_profile_links_rejects_invalid_url(bad):
    with pytest.raises(InvalidValueError):
        ProfileLinks(portfolio_url=bad)


# ---- WorkAuthorization (sensitive) ------------------------------------------


def test_work_authorization_is_flagged_sensitive():
    assert WorkAuthorization.SENSITIVE is True


def test_work_authorization_requires_a_status():
    auth = WorkAuthorization(
        status=WorkAuthorizationStatus.VISA_HOLDER, visa_type="H-1B"
    )
    assert auth.status is WorkAuthorizationStatus.VISA_HOLDER
    assert auth.visa_type == "H-1B"


# ---- EeoSelfIdentification (sensitive, optional, never defaulted) ----------


def test_eeo_self_identification_is_flagged_sensitive():
    assert EeoSelfIdentification.SENSITIVE is True


def test_eeo_self_identification_defaults_every_field_to_none():
    """Constructing one with no arguments must never assert an answer —
    every category defaults to "not provided", not a specific value or
    even the explicit "decline" option."""
    eeo = EeoSelfIdentification()
    assert eeo.gender_identity is None
    assert eeo.race_ethnicity is None
    assert eeo.veteran_status is None
    assert eeo.disability_status is None


def test_eeo_self_identification_accepts_explicit_answers():
    eeo = EeoSelfIdentification(
        gender_identity=GenderIdentity.FEMALE,
        race_ethnicity=RaceEthnicity.ASIAN,
        veteran_status=VeteranStatus.NOT_A_PROTECTED_VETERAN,
        disability_status=DisabilityStatus.DECLINE_TO_SELF_IDENTIFY,
    )
    assert eeo.gender_identity is GenderIdentity.FEMALE
    assert eeo.disability_status is DisabilityStatus.DECLINE_TO_SELF_IDENTIFY
