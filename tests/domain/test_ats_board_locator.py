"""Tests for identify_ats_board — the allowlist URL -> (provider, token)
parser backing AtsListingResolver's board discovery.

Explicitly proves LinkedIn/Indeed (and any other unrecognized domain)
never resolve to a board reference, structurally enforcing "never use
LinkedIn/Indeed" regardless of what a search result returns.
"""

from __future__ import annotations

import pytest

from src.domain.services.ats_board_locator import (
    AtsBoardReference,
    identify_ats_board,
)
from src.domain.value_objects.ats_provider import AtsProvider


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://boards.greenhouse.io/acme/jobs/123",
            AtsBoardReference(provider=AtsProvider.GREENHOUSE, board_token="acme"),
        ),
        (
            "https://job-boards.greenhouse.io/acme",
            AtsBoardReference(provider=AtsProvider.GREENHOUSE, board_token="acme"),
        ),
        (
            "https://jobs.lever.co/acme/some-uuid",
            AtsBoardReference(provider=AtsProvider.LEVER, board_token="acme"),
        ),
        (
            "https://jobs.ashbyhq.com/acme/some-uuid",
            AtsBoardReference(provider=AtsProvider.ASHBY, board_token="acme"),
        ),
    ],
)
def test_recognizes_supported_ats_board_urls(url: str, expected: AtsBoardReference):
    assert identify_ats_board(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/123456",
        "https://www.indeed.com/viewjob?jk=abc123",
        "https://acme.example.com/careers",
        "https://boards.greenhouse.io/",
    ],
)
def test_rejects_linkedin_indeed_and_any_unrecognized_domain(url: str):
    assert identify_ats_board(url) is None
