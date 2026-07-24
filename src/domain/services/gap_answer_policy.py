"""GapAnswerPolicy — a pure domain service that decides whether a
candidate's raw response to a gap-resolution question (see
`ResolveGapAnswer`) represents genuine experience worth remembering, or a
decline that must be omitted instead.

The gap-resolution loop's entire point is to surface *genuine* experience
without coaxing embellishment: a candidate who has nothing relevant to add
must be able to say so and have the gap cleanly disappear, never end up
with a fabricated or coerced "yes" on file. This policy is the single
place that recognizes a decline, so "nothing to add" is honored
consistently wherever an answer is captured (see `ResolveGapAnswer`).

Only exact, normalized matches against a fixed decline vocabulary count —
a real answer that happens to contain the substring "no" (e.g. "No, but I
mentored two interns") must never be misread as a decline, so this
deliberately does not do fuzzy/substring matching.
"""

from __future__ import annotations

_DECLINE_PHRASES = frozenset(
    {
        "",
        "no",
        "nope",
        "none",
        "n/a",
        "na",
        "nothing",
        "nothing to add",
        "not applicable",
        "not really",
        "no experience",
        "skip",
    }
)


class GapAnswerPolicy:
    """Recognizes a decline response to a gap-resolution question."""

    @staticmethod
    def is_declined(answer_text: str) -> bool:
        """True when `answer_text` is blank or exactly matches a known
        decline phrase (case/whitespace/trailing-punctuation insensitive).
        Anything else — including a short or hedged answer — is treated as
        a genuine response worth capturing."""
        normalized = answer_text.strip().lower().rstrip(".!")
        return normalized in _DECLINE_PHRASES
