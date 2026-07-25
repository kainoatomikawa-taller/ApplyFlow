"""AnswerSimilarityMatcher — a pure domain service for semantic retrieval
of remembered answers.

Reworded-but-equivalent questions ("Why do you want to work here?" vs
"What interests you about this role?") embed close together in vector
space even though their text differs, so matching by cosine similarity
between question embeddings — rather than exact string equality — is what
lets a previously-answered question be recognized again. Callers pass in
the candidate `AnswerMemory` records (already scoped to a user by the
repository); this service holds no I/O and knows nothing about how those
candidates were fetched.

The similarity threshold is a business rule (how close is "close enough"
to reuse an answer), so `DEFAULT_THRESHOLD` lives here — but it is
explicitly tunable per call via the `threshold` parameter, since the right
cutoff may need adjusting without a code change.

Two thresholds, because there are two questions
-----------------------------------------------
"Is this the same question, reworded?" and "is this answer relevant to what
the job asked about?" are different bars, and one cutoff cannot serve both.
Suppressing a re-ask demands near-equivalence (`DEFAULT_THRESHOLD`): asking
again is only wrong if the candidate has genuinely already answered *this*.
Picking which remembered answers a cover letter should draw on only needs
topical relatedness (`DEFAULT_RELEVANCE_THRESHOLD`) — "Have you led a team?"
is worth surfacing against a "Leadership experience" requirement while
scoring nowhere near an exact match. Holding the strict bar there would
surface nothing; holding the loose bar in the re-ask check would silently
skip questions the candidate never answered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

from src.domain.entities.answer_memory import AnswerMemory
from src.domain.exceptions import InvalidValueError


@dataclass(frozen=True)
class AnswerMatch:
    """A remembered answer retrieved as a semantic match, paired with its
    cosine-similarity score against the query question's embedding."""

    answer_memory: AnswerMemory
    similarity_score: float


class AnswerSimilarityMatcher:
    """Finds remembered answers matching a query by cosine similarity
    between embeddings."""

    #: "Same question, reworded" — the bar for treating a gap as already
    #: answered and not asking again.
    DEFAULT_THRESHOLD: ClassVar[float] = 0.85

    #: "Related to what this job asked about" — the bar for surfacing a
    #: remembered answer as material worth drawing on. Deliberately looser;
    #: see the module docstring.
    DEFAULT_RELEVANCE_THRESHOLD: ClassVar[float] = 0.6

    def find_best_match(
        self,
        question_embedding: list[float],
        candidates: list[AnswerMemory],
        threshold: float | None = None,
    ) -> AnswerMatch | None:
        """Return the highest-scoring candidate at or above `threshold`,
        or `None` if no candidate clears it (including when there are no
        candidates at all)."""
        effective_threshold = (
            self.DEFAULT_THRESHOLD if threshold is None else threshold
        )
        best: AnswerMatch | None = None
        for candidate in candidates:
            score = self.cosine_similarity(question_embedding, candidate.embedding)
            if score < effective_threshold:
                continue
            if best is None or score > best.similarity_score:
                best = AnswerMatch(answer_memory=candidate, similarity_score=score)
        return best

    def find_matches(
        self,
        query_embedding: list[float],
        candidates: list[AnswerMemory],
        threshold: float | None = None,
        limit: int | None = None,
    ) -> tuple[AnswerMatch, ...]:
        """Return every candidate at or above `threshold`, most similar
        first, capped at `limit` when given.

        The plural of `find_best_match`, for callers that want the several
        most relevant remembered answers rather than the single closest
        one — a cover letter drawing on a candidate's own words has room
        for a few, and which few depends on what the job asked about (see
        `RelevantAnswerSelector`).

        `limit` bounds a prompt rather than a result set: an unbounded list
        of answers would crowd out the profile facts it sits beside. A
        `limit` of 0 or less selects nothing, which is a caller asking for
        no highlighting rather than an error.
        """
        effective_threshold = self.DEFAULT_THRESHOLD if threshold is None else threshold
        if limit is not None and limit <= 0:
            return ()

        matches = [
            AnswerMatch(
                answer_memory=candidate,
                similarity_score=self.cosine_similarity(
                    query_embedding, candidate.embedding
                ),
            )
            for candidate in candidates
        ]
        ranked = sorted(
            (
                match
                for match in matches
                if match.similarity_score >= effective_threshold
            ),
            key=lambda match: match.similarity_score,
            reverse=True,
        )
        return tuple(ranked if limit is None else ranked[:limit])

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity of two equal-length, non-zero vectors, in
        [-1.0, 1.0]. A zero vector has no direction to compare, so it is
        defined here as similarity 0.0 to every vector rather than raising
        or dividing by zero."""
        if not a or not b:
            raise InvalidValueError("cosine_similarity requires non-empty vectors.")
        if len(a) != len(b):
            raise InvalidValueError(
                "cosine_similarity requires vectors of equal length — "
                f"got {len(a)} and {len(b)}."
            )
        dot = float(sum(x * y for x, y in zip(a, b, strict=True)))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
