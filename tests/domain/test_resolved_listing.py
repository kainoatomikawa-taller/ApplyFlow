import pytest

from src.domain.entities.resolved_listing import ResolvedListing
from src.domain.exceptions import InvalidValueError


def _resolved_listing(
    *,
    company: str = "Acme Corp",
    apply_url: str = "https://acme.example.com/careers",
    description: str = "Acme Corp's official careers page.",
    **kwargs,
) -> ResolvedListing:
    return ResolvedListing(
        company=company, apply_url=apply_url, description=description, **kwargs
    )


def test_valid_resolved_listing_constructs():
    resolved = _resolved_listing()
    assert resolved.company == "Acme Corp"
    assert resolved.apply_url == "https://acme.example.com/careers"


def test_normalized_company_is_derived():
    resolved = _resolved_listing(company="  Acme  Corp  ")
    assert resolved.normalized_company == "acme corp"


def test_empty_company_rejected():
    with pytest.raises(InvalidValueError):
        _resolved_listing(company="   ")


def test_empty_apply_url_rejected():
    with pytest.raises(InvalidValueError):
        _resolved_listing(apply_url="")


def test_empty_description_rejected():
    with pytest.raises(InvalidValueError):
        _resolved_listing(description="   ")
