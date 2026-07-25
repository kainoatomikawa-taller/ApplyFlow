"""ProvenanceGuard — the pure domain service that operationalizes "never
fabricate": generated output may only assert what the candidate's own
provenance-backed facts support, and anything else is stripped before the
output leaves the application.

`ProvenanceSource` states the contract for generated content (tailored
resumes, cover letters, autofilled answers): every claim has to trace back
to a `parsed_resume`, `user_entered`, or `answer` fact already in the data
model. Prompt instructions alone cannot enforce that — an LLM told "only
use these facts" still invents an employer, inflates a headcount, or
upgrades a degree. So the guard is a mechanical gate *after* generation,
not advice before it, and it is deliberately deterministic: no model gets
a vote on whether a claim about the candidate was fabricated.

How a line is checked
---------------------
Line by line, because a line is the smallest unit that can be dropped
without leaving a sentence fragment behind. Every *claim term* in the line
(anything that isn't neutral framing vocabulary — see `_NEUTRAL_TERMS`)
must be found in the supporting corpus:

- the candidate's `ProvenanceBackedFact`s, which is what actually
  discharges the provenance obligation, and
- `context_terms`: how the target job identifies itself — its title,
  company, and location. Naming the role applied for is not a claim
  *about the candidate*, so it needs no candidate provenance, but it
  still has to come from the stored posting rather than the model's
  imagination.

`context_terms` is strictly for that identifying handful, never the
posting's requirements or description. Feeding requirement text in would
quietly invert the whole guard: "I have deep Kubernetes experience" would
become self-justifying the moment the *job* mentioned Kubernetes, which is
precisely the fabrication this exists to stop. A requirement is what the
employer wants, never evidence about the candidate.

A line whose every claim term is found is kept, tagged with the provenance
sources of the facts that backed it. A line with even one unfindable term
is dropped and recorded as a `ProvenanceViolation` naming the exact terms
that failed, so the failure is debuggable rather than mysterious.

Numbers are never neutral: a headcount, salary, percentage, or year must
appear in the corpus verbatim, which is what stops "led a team of 5" from
becoming "led a team of 50". Terms are compared on a light inflectional
stem (`_stem`) so "engineers"/"engineering" match a fact's "engineer";
matching is otherwise exact, since loose matching is exactly how a
fabricated "Acmeworks" would pass for a real "Acme".

What this does and does not catch
---------------------------------
It reliably blocks *introduced* material: an employer, school, tool,
credential, or quantity that appears nowhere in the candidate's data
cannot survive, because its term has nothing to match. It does not attempt
semantic entailment, so it cannot catch a recombination of vocabulary that
is individually backed but jointly unstated ("led the migration at Acme"
assembled from a separate "led", "migration", and "Acme"). That residual
risk is why the generator prompts are also constrained to the supplied
facts: the guard is the floor, not the whole story, and a future
entailment verifier can layer on top through its own port without
changing this contract.

Stripping (rather than rejecting the whole document) is the default
because a single bad line should cost the candidate that line, not the
entire draft — but nothing is ever silently rewritten: every drop is
reported, and callers log them (see `GenerationGuardAudit`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact
from src.domain.value_objects.provenance_source import ProvenanceSource

#: A term: starts alphanumeric, may carry internal characters that are
#: part of real terms rather than punctuation ("c++", "c#", "3.5",
#: "2019-03-01", "u.s.", "co-op", "o'brien").
_TERM_RE = re.compile(r"[a-z0-9][a-z0-9+#'.\-]*")

#: Characters that join sub-terms inside one token, so "2019-03-01" also
#: contributes "2019", "03" and "01" to the corpus.
_SUB_TERM_RE = re.compile(r"[.\-/]")

#: Vocabulary that asserts nothing about the candidate's history: function
#: words, document scaffolding (resume section headings, letter salutation
#: and sign-off), and statements of interest/intent. A candidate saying
#: they are excited about a role is not claiming a fact about their past,
#: so requiring provenance for "excited" would only make the guard strip
#: every readable sentence. Anything that names a thing, a place, an
#: organization, a credential, or a quantity is NOT in here on purpose.
# fmt: off
_NEUTRAL_WORDS = frozenset(
    {
        # articles, pronouns, conjunctions, prepositions, auxiliaries
        "a", "about", "after", "all", "also", "an", "and", "any", "are",
        "as", "at", "be", "been", "both", "but", "by", "can", "could",
        "did", "do", "does", "during", "each", "for", "from", "had", "has",
        "have", "he", "her", "hers", "him", "his", "how", "i", "if", "in",
        "into", "is", "it", "its", "me", "more", "most", "my", "no", "not",
        "of", "on", "one", "or", "other", "our", "out", "over", "own",
        "she", "so", "some", "such", "than", "that", "the", "their",
        "them", "then", "there", "these", "they", "this", "those", "to",
        "up", "very", "was", "we", "were", "what", "when", "where",
        "which", "while", "who", "whom", "why", "will", "with", "would",
        "you", "your", "yours",
        # document scaffolding: resume headings, letter salutation/sign-off
        "additional", "application", "apply", "applying", "attached",
        "best", "candidate", "consideration", "contact", "cover", "dear",
        "details", "education", "email", "employment", "experience",
        "further", "highlights", "hiring", "history", "info",
        "information", "letter", "manager", "objective", "overview",
        "phone", "position", "profile", "qualifications", "recruiter",
        "references", "regards", "resume", "role", "section", "sincerely",
        "skills", "summary", "team", "thank", "thanks", "title", "work",
        # neutral statements of interest/intent — no factual claim
        "add", "am", "available", "believe", "bring", "consider", "discuss",
        "eager", "enjoy", "excited", "forward", "glad", "happy", "hearing",
        "help", "hope", "interest", "interested", "keen", "like", "look",
        "looking", "love", "opportunity", "please", "pleased", "reach",
        "seeking", "speak", "want", "welcome", "wish",
    }
)
# fmt: on


def _stem(term: str) -> str:
    """Collapse a term onto a light inflectional stem, applied identically
    to corpus and candidate text so "engineers"/"engineering" match a
    fact's "engineer".

    Short terms are left alone: acronyms and initialisms ("aws", "css",
    "r", "us") must not be mangled into each other, and the trailing-"s"
    rule would do exactly that. Digits fall through untouched, so numeric
    claims stay exact.
    """
    if term.endswith("'s"):
        term = term[:-2]
    if len(term) <= 3:
        return term
    for suffix, replacement in (
        ("ies", "y"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ):
        if term.endswith(suffix) and len(term) - len(suffix) >= 3:
            term = term[: len(term) - len(suffix)] + replacement
            break
    # "manage"/"manages"/"managed"/"managing" only converge once a
    # trailing vowel is dropped too; harmless because both sides of every
    # comparison get the same treatment.
    return term.rstrip("e") or term


def _terms(text: str) -> list[str]:
    """Every term in `text`, lowercased and in order of appearance.

    Trailing sentence punctuation is dropped so a fact's "Acme" backs a
    sentence-final "Acme." — but only trailing, so "3.5" and "u.s." keep
    the separators that are part of the term itself.
    """
    found: list[str] = []
    for raw in _TERM_RE.findall(text.lower()):
        term = raw.rstrip(".-'")
        if term:
            found.append(term)
    return found


def _index(text: str) -> set[str]:
    """The stems `text` contributes to the supporting corpus — whole terms
    plus the pieces of compound ones, so a fact's "2019-03-01" also backs
    a line's "2019"."""
    stems: set[str] = set()
    for term in _terms(text):
        stems.add(_stem(term))
        parts = [p for p in _SUB_TERM_RE.split(term) if p]
        if len(parts) > 1:
            stems.update(_stem(part) for part in parts)
    return stems


_NEUTRAL_TERMS = frozenset(_stem(word) for word in _NEUTRAL_WORDS)


def _is_neutral(term: str) -> bool:
    """True when `term` asserts nothing on its own. Digits are never
    neutral, however short: an unbacked number is the most consequential
    fabrication there is."""
    if any(character.isdigit() for character in term):
        return False
    return _stem(term) in _NEUTRAL_TERMS


@dataclass(frozen=True)
class SupportedLine:
    """One line cleared for output, with the provenance of the facts that
    backed its claims. `backing_sources` is empty for a line that made no
    claim about the candidate at all (a blank separator, a section
    heading, "Dear Hiring Manager,") — honest reporting rather than an
    implied source."""

    text: str
    backing_sources: tuple[ProvenanceSource, ...] = ()


@dataclass(frozen=True)
class ProvenanceViolation:
    """One dropped line, naming the terms that nothing in the corpus
    backed. Carries the line verbatim: it is precisely what a developer
    needs to see, and being unbacked, it is model invention rather than
    candidate data."""

    line: str
    unsupported_terms: tuple[str, ...]


@dataclass(frozen=True)
class GuardedContent:
    """The result of guarding one generated document: what survived, and
    what was taken out and why."""

    lines: tuple[SupportedLine, ...] = ()
    violations: tuple[ProvenanceViolation, ...] = ()

    @property
    def content(self) -> str:
        """The output text, unsupported lines removed and nothing
        rewritten — surviving lines are byte-identical to what was
        generated."""
        return "\n".join(line.text for line in self.lines)

    @property
    def backing_sources(self) -> tuple[ProvenanceSource, ...]:
        """Every provenance source the surviving content traces to, in
        `ProvenanceSource` declaration order."""
        present = {source for line in self.lines for source in line.backing_sources}
        return tuple(source for source in ProvenanceSource if source in present)

    @property
    def is_clean(self) -> bool:
        """True when the generator produced nothing that needed removing."""
        return not self.violations


class ProvenanceGuard:
    """Validates generated content against provenance-backed facts and
    strips whatever they don't support."""

    def enforce(
        self,
        content: str,
        *,
        facts: tuple[ProvenanceBackedFact, ...],
        context_terms: tuple[str, ...] = (),
    ) -> GuardedContent:
        """Return `content` reduced to the lines its supporting corpus
        backs, plus a violation per dropped line.

        `facts` is the candidate's provenance-backed ground truth.
        `context_terms` is how the posting identifies itself — title,
        company, location — and nothing else; see the module docstring for
        why passing requirement text here would defeat the guard. With no
        facts and no context, nothing that asserts anything survives —
        which is the correct outcome, not a degenerate one: there is
        nothing on file to justify a single claim.
        """
        fact_index = tuple((fact, _index(fact.text)) for fact in facts)
        context_index: set[str] = set()
        for term in context_terms:
            context_index |= _index(term)

        lines: list[SupportedLine] = []
        violations: list[ProvenanceViolation] = []

        for line in content.splitlines():
            if not line.strip():
                lines.append(SupportedLine(text=line))
                continue
            backing, unsupported = self._check_line(line, fact_index, context_index)
            if unsupported:
                violations.append(
                    ProvenanceViolation(line=line, unsupported_terms=unsupported)
                )
                continue
            lines.append(SupportedLine(text=line, backing_sources=backing))

        return GuardedContent(lines=tuple(lines), violations=tuple(violations))

    def _check_line(
        self,
        line: str,
        fact_index: tuple[tuple[ProvenanceBackedFact, set[str]], ...],
        context_index: set[str],
    ) -> tuple[tuple[ProvenanceSource, ...], tuple[str, ...]]:
        """Split one line's claim terms into the provenance sources
        backing them and the terms nothing backed."""
        backing: set[ProvenanceSource] = set()
        unsupported: list[str] = []

        for term in _terms(line):
            if _is_neutral(term):
                continue
            sources = self._sources_backing(term, fact_index)
            if sources:
                backing |= sources
                continue
            if self._is_in_corpus(term, context_index):
                continue
            if term not in unsupported:
                unsupported.append(term)

        ordered_backing = tuple(
            source for source in ProvenanceSource if source in backing
        )
        return ordered_backing, tuple(unsupported)

    def _sources_backing(
        self,
        term: str,
        fact_index: tuple[tuple[ProvenanceBackedFact, set[str]], ...],
    ) -> set[ProvenanceSource]:
        return {
            fact.source for fact, stems in fact_index if self._is_in_corpus(term, stems)
        }

    @staticmethod
    def _is_in_corpus(term: str, corpus: set[str]) -> bool:
        """A term is in the corpus when its stem is, or — for a compound
        term like "2019-2021" or "react/redux" — when every one of its
        pieces is."""
        if _stem(term) in corpus:
            return True
        parts = [part for part in _SUB_TERM_RE.split(term) if part]
        if len(parts) < 2:
            return False
        return all(_stem(part) in corpus for part in parts)
