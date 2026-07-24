"""LinkCheckOutcome — the result of one reachability probe against a
`JobPosting`'s `apply_url` (see `ApplyUrlCheckerPort`), consumed by
`JobPosting.apply_link_check`.

CONFIRMED_DEAD is reserved for responses a server uses to unambiguously
assert a resource is gone (404 Not Found, 410 Gone), so it flags a
posting DEAD_LINK on the very first occurrence. TRANSIENT_FAILURE covers
everything else that failed to confirm reachability (timeouts, connection
errors, 5xx) — ambiguous, so it only counts toward a consecutive-failure
threshold rather than flagging immediately, since these commonly reflect
a temporary blip rather than the posting actually being gone.
"""

from __future__ import annotations

from enum import StrEnum


class LinkCheckOutcome(StrEnum):
    REACHABLE = "reachable"
    CONFIRMED_DEAD = "confirmed_dead"
    TRANSIENT_FAILURE = "transient_failure"
