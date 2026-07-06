import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.match_score import MatchScore


def test_email_is_normalized():
    assert EmailAddress("  JANE@Example.COM ").value == "jane@example.com"


@pytest.mark.parametrize("bad", ["no-at", "a@b", "@b.com", ""])
def test_invalid_email_rejected(bad):
    with pytest.raises(InvalidValueError):
        EmailAddress(bad)


@pytest.mark.parametrize("bad", [-1, 101, 200])
def test_match_score_bounds(bad):
    with pytest.raises(InvalidValueError):
        MatchScore(bad)


def test_strong_match_threshold():
    assert MatchScore(75).is_strong_match
    assert not MatchScore(74).is_strong_match
