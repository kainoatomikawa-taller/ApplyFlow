"""JobPostingStatus — the lifecycle of a `JobPosting`'s visibility to
candidates.

One-way: once a posting leaves ACTIVE it never returns. Both STALE
(presumed expired by age) and DEAD_LINK (apply_url confirmed, or
repeatedly found, unreachable) are terminal — reactivating a posting that
already looked expired or dead risks resurfacing a job a candidate can no
longer actually apply to. See `JobPosting.mark_stale_if_expired` and
`JobPosting.apply_link_check`, which are the only things that change this
value and both enforce the one-way rule.
"""

from __future__ import annotations

from enum import StrEnum


class JobPostingStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    DEAD_LINK = "dead_link"
