"""resolve_profile_field — what the candidate's stored record can state for
one `ApplicationFieldSlot`.

The other half of field mapping. `recognize_application_field` answers "what
is this field asking?"; this answers "what does the candidate's record say
about that?" — and, just as importantly, when it says nothing.

Never invents, and says when it inferred
----------------------------------------
`None` means the profile does not answer this slot, and it is returned
freely: an absent phone number, an empty address, no education on file. A
caller must surface those fields rather than fill them, so silence here is
what keeps a blank on file from becoming a plausible-looking blank on an
application. This is the same rule `ProvenanceSource` states for generated
documents — an autofilled answer may only assert what the candidate's data
actually contains — applied to form fields.

A few slots are answered by *rearranging* stored facts rather than reading
one, and those come back flagged `is_derived` so a review step can put a
human's attention exactly where the record was interpreted:

- **First/last name**, split out of the one `full_name` the profile stores.
- **Location**, composed from the address when no explicit location is set.

`is_derived` is not a confidence score. Every derived value is built purely
from what the candidate provided; the flag marks the ones where ApplyFlow
chose *how* to present it.

Why the name split is the way it is
-----------------------------------
`_split_name` treats the final whitespace-separated token as the family name
and everything before it as the given name(s). That is right for the common
two- and three-token Western cases and wrong for others — Spanish and
Portuguese names carry two surnames, so "Maria García Pérez" yields a given
name of "Maria García". No rule over a single stored string gets every name
right, and the alternatives are worse: refusing to split at all would leave
first/last name — on nearly every form in existence — permanently blank,
and asking the model to guess would put a fabricated legal name on a legal
document. So the split is performed, flagged as derived, and shown to the
candidate before anything is submitted. A single-token name is not split at
all (there is no family name to take), and comes back as `None`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    is_sensitive_slot,
)


@dataclass(frozen=True)
class ProfileFieldValue:
    """A value the candidate's record supports for one slot."""

    text: str
    #: True when the value was rearranged out of stored facts rather than
    #: read from one field — see the module docstring.
    is_derived: bool = False


#: Reads one slot's answer out of a profile, or returns None when the
#: profile has nothing to say about it.
_SlotResolver = Callable[[UserProfile], ProfileFieldValue | None]


def resolve_profile_field(
    profile: UserProfile, slot: ApplicationFieldSlot
) -> ProfileFieldValue | None:
    """Return what `profile` can state for `slot`, or None if it cannot.

    Returns None for every sensitive slot, whatever the profile holds. That
    is a refusal rather than an absence: sensitive fields are governed by
    `decide_sensitive_field`, which applies rules this function has no
    business duplicating — attestation, exact-or-refuse answers, and the
    unconditional refusal of EEO self-identification.

    The check is here rather than only in the caller so the two paths cannot
    be crossed by accident. A contributor who routes a visa question through
    the ordinary resolver gets nothing back, not a quietly-filled legal
    declaration.
    """
    if is_sensitive_slot(slot):
        return None

    resolver = _RESOLVERS.get(slot)
    if resolver is None:
        # A recognized slot with nothing in the profile that answers it.
        # MIDDLE_NAME and PREFERRED_NAME used to be here; the profile now holds
        # both (see `_middle_name`/`_preferred_name`). What is left is the
        # document slots, answered from a stored `ApplicationDocument` and so
        # deliberately not this function's business.
        return None
    return resolver(profile)


# ---- Identity ----------------------------------------------------------------


def _full_name(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.full_name)


def _first_name(profile: UserProfile) -> ProfileFieldValue | None:
    split = _split_name(profile.full_name)
    return ProfileFieldValue(split[0], is_derived=True) if split else None


def _last_name(profile: UserProfile) -> ProfileFieldValue | None:
    split = _split_name(profile.full_name)
    return ProfileFieldValue(split[1], is_derived=True) if split else None


def _middle_name(profile: UserProfile) -> ProfileFieldValue | None:
    """The candidate's middle name, or a positive "I have none".

    The empty answer is the interesting case. A blank `middle_name` on the
    profile means the candidate has none — not that they forgot to tell us — so
    this returns an *answered* value that happens to be empty rather than None.

    The difference matters at the other end: None means "the profile cannot
    answer this", which sends the question to the candidate on every application
    they ever fill. An empty answer means "the answer is nothing", which leaves
    the box blank and stops asking. Plenty of people have no middle name, and a
    form field they must dismiss on every application is a worse outcome than a
    field left empty.

    `AtsFormFieldPlanner` is where that reading is acted on, including the one
    case it cannot honor: a field the portal marks *required*, where writing
    nothing would fail the portal's own validation and the candidate has to
    decide what to put.
    """
    return ProfileFieldValue(profile.middle_name or "")


def _preferred_name(profile: UserProfile) -> ProfileFieldValue | None:
    """The name the candidate goes by, falling back to their first name.

    A blank `preferred_name` means "the same name I go by legally", so the answer
    is the first name split out of `full_name` — not the whole legal name. ATS
    "preferred name" fields expect "Mike", not "Michael Andrew Smith".

    Flagged derived in both the fallback case (assembled from `full_name`) and
    never in the stated case, so a review screen can distinguish a name the
    candidate typed from one inferred for them.
    """
    if profile.preferred_name:
        return ProfileFieldValue(profile.preferred_name)
    return _first_name(profile)


def _split_name(full_name: str) -> tuple[str, str] | None:
    """Split a stored full name into (given names, family name), or None
    when there is only one token to work with."""
    tokens = full_name.split()
    if len(tokens) < 2:
        return None
    return " ".join(tokens[:-1]), tokens[-1]


# ---- Contact -----------------------------------------------------------------


def _email(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.email.value)


def _phone(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.phone)


def _location(profile: UserProfile) -> ProfileFieldValue | None:
    """The candidate's location, preferring the field they filled in.

    Falls back to composing city/state/country from the address, because a
    form asking for one free-text location and a profile carrying a
    structured address are describing the same fact in two shapes.
    """
    explicit = _verbatim(profile.location)
    if explicit is not None:
        return explicit

    address = profile.address
    parts = [
        part
        for part in (address.city, address.state_or_region, address.country)
        if part and part.strip()
    ]
    if not parts:
        return None
    return ProfileFieldValue(", ".join(part.strip() for part in parts), is_derived=True)


# ---- Current employment ------------------------------------------------------


def _current_company(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _current_or_latest_role(profile)
    return _verbatim(entry.company_name) if entry else None


def _current_title(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _current_or_latest_role(profile)
    return _verbatim(entry.job_title) if entry else None


def _current_or_latest_role(profile: UserProfile) -> WorkHistoryEntry | None:
    """The role a form means by "current": an ongoing one if the candidate
    has one, otherwise the most recently started.

    Falling back to the latest past role rather than returning nothing keeps
    a between-jobs candidate from having the field blanked — the form is
    asking where they most recently worked, and the record answers that.
    """
    if not profile.work_history:
        return None
    ongoing = [entry for entry in profile.work_history if entry.is_current]
    candidates = ongoing or profile.work_history
    return max(candidates, key=lambda entry: entry.start_date)


# ---- Address -----------------------------------------------------------------


def _street_address(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.address.street_address)


def _city(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.address.city)


def _state_or_region(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.address.state_or_region)


def _postal_code(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.address.postal_code)


def _country(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.address.country)


# ---- Links -------------------------------------------------------------------


def _linkedin_url(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.links.linkedin_url)


def _github_url(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.links.github_url)


def _portfolio_url(profile: UserProfile) -> ProfileFieldValue | None:
    return _verbatim(profile.links.portfolio_url)


# ---- Education ---------------------------------------------------------------


def _school(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    return _verbatim(entry.institution_name) if entry else None


def _degree(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    return _verbatim(entry.degree) if entry else None


def _field_of_study(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    # `field_of_study` is the majors joined — a form asking for one field of
    # study on a double major gets both, which is accurate, where picking one
    # would silently drop a qualification.
    return _verbatim(entry.field_of_study) if entry else None


def _minor(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    if entry is None or not entry.minors:
        return None
    return _verbatim(", ".join(entry.minors))


#: Slots whose answer is a field of study, and which therefore have a list of
#: individual subjects behind the single string `resolve_profile_field` returns.
_SUBJECT_SLOTS: dict[ApplicationFieldSlot, str] = {
    ApplicationFieldSlot.FIELD_OF_STUDY: "majors",
    ApplicationFieldSlot.MINOR: "minors",
}


def subject_candidates(
    profile: UserProfile, slot: ApplicationFieldSlot
) -> tuple[str, ...]:
    """The individual subjects behind a field-of-study slot, in the candidate's
    own order — a first major before a second.

    `resolve_profile_field` joins these for the single text box a form usually
    offers. A caller facing a *dropdown* needs them apart, because one of them
    may be listed while the joined string never is. Empty for every other slot,
    so a caller can ask without first checking whether asking makes sense.
    """
    entry = _most_recent_education(profile)
    attribute = _SUBJECT_SLOTS.get(slot)
    if entry is None or attribute is None:
        return ()
    subjects: tuple[str, ...] = getattr(entry, attribute)
    return subjects


def _education_start_date(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    return _iso_date(entry.start_date) if entry else None


def _education_end_date(profile: UserProfile) -> ProfileFieldValue | None:
    entry = _most_recent_education(profile)
    return _iso_date(entry.end_date) if entry else None


def _most_recent_education(profile: UserProfile) -> EducationEntry | None:
    """The candidate's latest program of study.

    Application forms present one education block by default and repeat it
    only on request, so the single block a mapper can fill should hold the
    most recent qualification. Ordered by end date, falling back to start
    date for a program still in progress; undated entries sort last and are
    only chosen when nothing else is on file.
    """
    if not profile.education:
        return None
    return max(
        profile.education,
        key=lambda entry: entry.end_date or entry.start_date or date.min,
    )


# ---- Shared helpers ----------------------------------------------------------


def _verbatim(value: str | None) -> ProfileFieldValue | None:
    """Wrap a stored string, treating blank and absent identically — a field
    holding only whitespace is not a fact the candidate stated."""
    if value is None or not value.strip():
        return None
    return ProfileFieldValue(value.strip())


def _iso_date(value: date | None) -> ProfileFieldValue | None:
    """Render a stored date unambiguously (`YYYY-MM-DD`).

    ISO because it is what an `<input type="date">` requires and the only
    format with no reading that silently swaps day and month. A portal
    wanting something else will refuse the value rather than record the
    wrong date (see `RejectedFieldValueError`), which is the outcome to
    prefer.
    """
    return ProfileFieldValue(value.isoformat()) if value is not None else None


#: Slot → the function that answers it from a profile. A slot absent from
#: this table is one no stored profile data answers; `resolve_profile_field`
#: returns None for those rather than treating the gap as an error.
_RESOLVERS: dict[ApplicationFieldSlot, _SlotResolver] = {
    ApplicationFieldSlot.FULL_NAME: _full_name,
    ApplicationFieldSlot.FIRST_NAME: _first_name,
    ApplicationFieldSlot.LAST_NAME: _last_name,
    ApplicationFieldSlot.MIDDLE_NAME: _middle_name,
    ApplicationFieldSlot.PREFERRED_NAME: _preferred_name,
    ApplicationFieldSlot.EMAIL: _email,
    ApplicationFieldSlot.PHONE: _phone,
    ApplicationFieldSlot.LOCATION: _location,
    ApplicationFieldSlot.STREET_ADDRESS: _street_address,
    ApplicationFieldSlot.CITY: _city,
    ApplicationFieldSlot.STATE_OR_REGION: _state_or_region,
    ApplicationFieldSlot.POSTAL_CODE: _postal_code,
    ApplicationFieldSlot.COUNTRY: _country,
    ApplicationFieldSlot.LINKEDIN_URL: _linkedin_url,
    ApplicationFieldSlot.GITHUB_URL: _github_url,
    ApplicationFieldSlot.PORTFOLIO_URL: _portfolio_url,
    ApplicationFieldSlot.CURRENT_COMPANY: _current_company,
    ApplicationFieldSlot.CURRENT_TITLE: _current_title,
    ApplicationFieldSlot.SCHOOL: _school,
    ApplicationFieldSlot.DEGREE: _degree,
    ApplicationFieldSlot.FIELD_OF_STUDY: _field_of_study,
    ApplicationFieldSlot.MINOR: _minor,
    ApplicationFieldSlot.EDUCATION_START_DATE: _education_start_date,
    ApplicationFieldSlot.EDUCATION_END_DATE: _education_end_date,
}
