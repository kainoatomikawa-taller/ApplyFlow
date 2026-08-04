"""Matching a stated field of study against the options a dropdown offers.

Application forms routinely list majors at a coarser grain than people study
them. An Applied Mathematics graduate meets a `<select>` whose closest entry is
"Mathematics"; a Data Analytics graduate meets one listing "Data Science". Left
alone, the exact major matches nothing and the field is refused, so the candidate
retypes the same answer on every application.

The rule this implements is narrow on purpose:

**A broader category is chosen only when the exact subject is not on offer.**
If "Applied Mathematics" is listed, "Applied Mathematics" is what gets selected —
the broader "Mathematics" is never preferred over an available exact answer. That
ordering is the whole point, and `is_exact` on the result is what lets a caller
show a broadened answer as inferred rather than as something the candidate typed.

How a broader category is found
-------------------------------
Two mechanisms, tried in order of how much they assume.

1. **Head-noun suffix.** In English the head of a noun phrase is last, so the
   category a subject belongs to is a *trailing* run of its words: "Applied
   Mathematics" → "Mathematics", "Computer Engineering" → "Engineering". Matching
   a suffix rather than any substring is what keeps "Mathematics Education" out
   of "Mathematics" — that degree is in Education, and a form answer claiming
   otherwise would misstate it. The longest matching suffix wins, so a form
   offering both "Computer Engineering" and "Engineering" gets the former.

2. **A curated table**, for relationships no amount of word-matching can derive:
   abbreviations ("Poli Sci"), and sibling or parent subjects that forms use
   interchangeably ("Data Analytics" where the form says "Data Science"). Parents
   are listed most-specific-first, so the choice is deterministic rather than
   dependent on the order the form happens to list its options in.

The table is deliberately small and conservative. Every entry asserts something
about a real person's education on a real application, so a wrong entry is worse
than a missing one — a missing entry only means the field gets surfaced for the
candidate to answer, which is what happens today for everything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SubjectOptionMatch:
    """An option the subject can be answered with."""

    #: The option text to write, exactly as the form spelled it.
    option: str
    #: True when the option names the subject itself (allowing for case and
    #: spacing); False when it is a broader or equivalent category standing in
    #: for it. Callers surface the latter as an inferred value.
    is_exact: bool
    #: The subject this came from. With several majors on one entry, this says
    #: which one the answer speaks for.
    subject: str


def normalize_subject(value: str) -> str:
    """Casefold, collapse whitespace, and drop punctuation that only ever varies
    by house style — never used as a value to write, only to compare."""
    cleaned = [
        character.casefold()
        for character in value
        if character.isalnum() or character.isspace()
    ]
    return " ".join("".join(cleaned).split())


#: Subjects that mean the same thing as an option spelled differently —
#: abbreviations and the shorthand people type. Keys are normalized.
_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "cs": ("Computer Science",),
    "comp sci": ("Computer Science",),
    "compsci": ("Computer Science",),
    "math": ("Mathematics",),
    "maths": ("Mathematics",),
    "stats": ("Statistics",),
    "poli sci": ("Political Science",),
    "polisci": ("Political Science",),
    "econ": ("Economics",),
    "psych": ("Psychology",),
    "bio": ("Biology",),
    "chem": ("Chemistry",),
    "mech e": ("Mechanical Engineering",),
    "mech eng": ("Mechanical Engineering",),
    "ee": ("Electrical Engineering",),
    "elec eng": ("Electrical Engineering",),
    "me": ("Mechanical Engineering",),
    "business admin": ("Business Administration",),
}

#: Categories a subject can honestly be filed under when the subject itself is
#: not offered, most specific first. Only for relationships the head-noun rule
#: cannot reach: siblings forms treat as interchangeable, and parents whose name
#: is not a trailing word of the subject.
_BROADER_CATEGORIES: dict[str, tuple[str, ...]] = {
    # The pair this was written for, in both directions: forms use one name or
    # the other, rarely both.
    "data analytics": ("Data Science", "Statistics", "Mathematics"),
    "data science": ("Data Analytics", "Statistics", "Mathematics"),
    "business analytics": ("Business Analytics", "Business Administration"),
    "software engineering": ("Computer Science", "Engineering"),
    "computer information systems": ("Information Systems", "Computer Science"),
    "management information systems": ("Information Systems",),
    "information technology": ("Information Systems", "Computer Science"),
    "biochemistry": ("Biochemistry", "Chemistry", "Biology"),
    "neuroscience": ("Neuroscience", "Biology", "Psychology"),
    "econometrics": ("Economics", "Statistics"),
    "accounting": ("Accounting", "Business Administration"),
    "finance": ("Finance", "Business Administration"),
    "marketing": ("Marketing", "Business Administration"),
}


def _suffix_runs(tokens: Sequence[str]) -> list[str]:
    """Every trailing run of `tokens`, longest first.

    Excludes the whole phrase: that is the exact subject, which has already been
    tried by the time broadening is reached, and which would not be *broader*.
    """
    return [" ".join(tokens[start:]) for start in range(1, len(tokens))]


def _lookup(options_by_text: dict[str, str], names: Sequence[str]) -> str | None:
    """The first of `names` the form actually offers, or None."""
    for name in names:
        offered = options_by_text.get(normalize_subject(name))
        if offered is not None:
            return offered
    return None


def match_subject_options(
    subjects: Sequence[str], options: Sequence[str]
) -> SubjectOptionMatch | None:
    """Pick the option that best answers one of `subjects`, or None.

    `subjects` is ordered by the candidate's own priority — a first major before
    a second — and an exact match on *any* of them beats a broadened match on all
    of them. That ordering is what makes a double major on a single-choice
    dropdown behave: if either major is listed, it is selected verbatim, and only
    when neither is does a broader category come into play.

    Returns None when nothing fits, which leaves the field to be refused and
    surfaced. Guessing would be the one outcome worse than asking.
    """
    # Keyed by normalized text so a form spelling it "COMPUTER SCIENCE" still
    # resolves, while the value written back keeps the form's own spelling.
    options_by_text: dict[str, str] = {}
    for option in options:
        key = normalize_subject(option)
        if not key or key in options_by_text:
            continue
        options_by_text[key] = option

    if not options_by_text:
        return None

    cleaned = [subject for subject in subjects if normalize_subject(subject)]

    # Pass 1: an exact match on any subject, in the candidate's own order. This
    # runs to completion across every subject before any broadening is tried —
    # that is the "if and only if" the whole module rests on.
    for subject in cleaned:
        offered = options_by_text.get(normalize_subject(subject))
        if offered is not None:
            return SubjectOptionMatch(option=offered, is_exact=True, subject=subject)

    # Pass 2: equivalents — a different spelling of the same subject, so still
    # not a broadening, but not verbatim either.
    for subject in cleaned:
        offered = _lookup(
            options_by_text, _EQUIVALENTS.get(normalize_subject(subject), ())
        )
        if offered is not None:
            return SubjectOptionMatch(option=offered, is_exact=False, subject=subject)

    # Pass 3: the head-noun suffix, longest first. Preferred over the curated
    # table because a trailing word of the subject is evidence from the subject
    # itself rather than an assumption made on its behalf.
    for subject in cleaned:
        for text in _suffix_runs(normalize_subject(subject).split()):
            offered = options_by_text.get(text)
            if offered is not None:
                return SubjectOptionMatch(
                    option=offered, is_exact=False, subject=subject
                )

    # Pass 4: the curated categories.
    for subject in cleaned:
        offered = _lookup(
            options_by_text, _BROADER_CATEGORIES.get(normalize_subject(subject), ())
        )
        if offered is not None:
            return SubjectOptionMatch(option=offered, is_exact=False, subject=subject)

    return None
