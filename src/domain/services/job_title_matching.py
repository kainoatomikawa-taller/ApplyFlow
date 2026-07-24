"""titles_match — decides whether an ATS board listing's title counts as
the same role as the aggregator listing that triggered a resolution.

Not exact-string equality: ATS boards commonly render a title with a
team/level qualifier the aggregator's copy lacks (e.g. "Backend Engineer"
on Adzuna vs. "Backend Engineer, Platform" on the company's own board), so
this normalizes both sides (see `normalize_text`) and accepts either being
a substring of the other.
"""

from __future__ import annotations

from src.domain.services.text_normalization import normalize_text


def titles_match(a: str, b: str) -> bool:
    normalized_a = normalize_text(a)
    normalized_b = normalize_text(b)
    if not normalized_a or not normalized_b:
        return False
    return (
        normalized_a == normalized_b
        or normalized_a in normalized_b
        or normalized_b in normalized_a
    )
