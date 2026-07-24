"""Shared text-normalization helper for deriving stable dedup/cache keys.

Used by `JobPosting` (dedup across aggregator sources) and
`ResolvedCompanyBoard` (the search-API board-discovery cache, keyed on
company alone) so both entities collapse a display string the same way:
trimmed, lowercased, whitespace-collapsed. Not fuzzy matching — just
enough to catch the same name rendered with different casing/spacing.
"""

from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip().lower())
