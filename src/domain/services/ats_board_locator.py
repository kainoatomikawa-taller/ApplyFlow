"""identify_ats_board — recognizes which of the three supported ATS
platforms (Greenhouse, Lever, Ashby) a public job-board URL belongs to,
and extracts that board's token from the path.

This is an ALLOWLIST, not a blocklist: only these three domains are ever
recognized as a company's board. A LinkedIn or Indeed URL — or any other
domain a search result might turn up — falls through to `None` exactly
like a typo or an unrelated result would; no special-case exclusion logic
is needed to keep them out, because nothing outside the allowlist can
ever resolve to a board reference in the first place. This is the
structural half of the "never use LinkedIn/Indeed" rule (the other half
is that the locating search query itself is restricted to these three
domains — see `AtsListingResolver`).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from src.domain.value_objects.ats_provider import AtsProvider

#: Hostnames recognized as a public ATS board, mapped to the provider that
#: serves them. Greenhouse has migrated some boards from `boards.` to
#: `job-boards.`; both are accepted.
_HOST_PROVIDERS: dict[str, AtsProvider] = {
    "boards.greenhouse.io": AtsProvider.GREENHOUSE,
    "job-boards.greenhouse.io": AtsProvider.GREENHOUSE,
    "jobs.lever.co": AtsProvider.LEVER,
    "jobs.ashbyhq.com": AtsProvider.ASHBY,
}


@dataclass(frozen=True)
class AtsBoardReference:
    """A company's board, identified by platform + the token that scopes
    that platform's public API/URLs to this company alone."""

    provider: AtsProvider
    board_token: str


def identify_ats_board(url: str) -> AtsBoardReference | None:
    """Return the ATS board `url` points at, or None if it isn't a
    recognized Greenhouse/Lever/Ashby board URL."""
    parsed = urlparse(url)
    provider = _HOST_PROVIDERS.get(parsed.netloc.lower())
    if provider is None:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None

    return AtsBoardReference(provider=provider, board_token=segments[0])
