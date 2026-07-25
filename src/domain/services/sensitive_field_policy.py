"""decide_sensitive_field — the single place that decides what, if anything,
ApplyFlow may put into a sensitive field on an application form.

Two categories, opposite rules
------------------------------
**EEO self-identification is never answered.** Not when the profile is empty,
not when it is full, not when the field is marked required. The refusal is
unconditional and is the first thing this function checks, before it looks at
any data (see `REQUIRES_CANDIDATE_ANSWER` for the reasoning: disclosure is
voluntary and is a per-application decision, so carrying an answer forward
would silently convert one disclosure into a standing one).

**Work authorization is answered whenever the record answers it exactly.**
The opposite failure matters here: an unanswered authorization question stalls
a required field and the application goes nowhere, so declining to answer is
not the safe default it is for EEO. What *is* unsafe is answering
approximately — so every answer below is either exact or refused, and the
refusal carries a reason the candidate can act on.

Three gates before any legal answer is produced
-----------------------------------------------
1. **On file.** No `WorkAuthorization` record, no answer.
2. **Candidate-attested.** The record's provenance must be the candidate's own
   statement, never a resume parse — see `WorkAuthorization.ATTESTING_SOURCES`.
3. **Unambiguous.** The stored data must settle *this specific question*. A
   `VISA_HOLDER` status does not settle "will you ever need sponsorship", and
   an `OTHER` status settles nothing at all; both are refused rather than
   guessed.

Yes/No answers are the literal strings "Yes" and "No", which is what these
questions are labelled with across Greenhouse, Lever, and Ashby. The browser
harness matches an option by its exact label or submitted value (normalized
for case and whitespace only, never fuzzy), so a portal phrasing its options
differently — "Yes, I am authorized" — refuses the value and hands back the
options that would have worked, rather than selecting the nearest one. On
these fields in particular, "nearest" is a misstatement.

Known limitation: jurisdiction
------------------------------
These questions almost always name a country ("authorized to work in the
United States"), and `WorkAuthorization` does not record which jurisdiction
its status refers to. The answers below therefore read the record as the
candidate's answer to the standard application question — which is what those
profile fields exist for — and cannot detect a candidate whose stored status
applies to a different country than the form is asking about.

Guarding on `citizenship_country` was considered and rejected: it would
falsely refuse every visa holder, whose citizenship country is by definition
not the country they are authorized in, and blanking a correct "Yes" is its
own harm. Fixing this properly means recording the jurisdiction on
`WorkAuthorization` (an Epic 01 data-model change). Until then the safeguard
is the review step: every filled legal answer is flagged
`requires_confirmation` so the candidate sees it before anything is
submitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    is_sensitive_slot,
    requires_candidate_answer,
)
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus

#: What a yes/no legal question is answered with. Bare "Yes"/"No" is how
#: Greenhouse, Lever, and Ashby label these options; anything else is refused
#: by the harness rather than approximated.
_YES = "Yes"
_NO = "No"

#: Statuses that state the candidate is authorized to work, and those that
#: state they are not. A status absent from both settles nothing (`OTHER`) and
#: is refused as `NOT_DERIVABLE`.
_AUTHORIZED_STATUSES: frozenset[WorkAuthorizationStatus] = frozenset(
    {
        WorkAuthorizationStatus.CITIZEN,
        WorkAuthorizationStatus.PERMANENT_RESIDENT,
        # A visa holder holds authorization now. Whether it will need renewing
        # or transferring is the *sponsorship* question, answered separately
        # and refused for this status.
        WorkAuthorizationStatus.VISA_HOLDER,
    }
)
_UNAUTHORIZED_STATUSES: frozenset[WorkAuthorizationStatus] = frozenset(
    {
        # "Requires sponsorship" means not authorized as things stand — that
        # is what needing a sponsor is.
        WorkAuthorizationStatus.REQUIRES_SPONSORSHIP,
        WorkAuthorizationStatus.NOT_AUTHORIZED,
    }
)

#: Statuses that settle the sponsorship question on their own, used only when
#: the candidate did not answer it explicitly.
#:
#: Deliberately excludes `VISA_HOLDER` and `NOT_AUTHORIZED`. The question is
#: almost always "now **or in the future**", and a visa can expire, need
#: transferring to a new employer, or need extending — so a current visa says
#: nothing reliable about the future, and someone not currently authorized may
#: or may not need this employer to sponsor them. Both are refused so the
#: candidate answers.
_SPONSORSHIP_FROM_STATUS: dict[WorkAuthorizationStatus, str] = {
    WorkAuthorizationStatus.CITIZEN: _NO,
    WorkAuthorizationStatus.PERMANENT_RESIDENT: _NO,
    WorkAuthorizationStatus.REQUIRES_SPONSORSHIP: _YES,
}


class SensitiveFieldRefusal(StrEnum):
    """Why a sensitive field was not answered.

    Distinct reasons because they call for different things from the
    candidate: fill in your profile, confirm what's already there, answer
    this one yourself.
    """

    #: EEO self-identification. Unconditional, and never about the data.
    CANDIDATE_CHOICE_ONLY = "candidate_choice_only"
    #: No work-authorization record on file at all. Fixed once, on the
    #: profile, for every future application.
    NOT_ON_FILE = "not_on_file"
    #: A record exists but does not state this particular field.
    NOT_STATED = "not_stated"
    #: A record exists and the candidate did not state it themselves — see
    #: `WorkAuthorization.ATTESTING_SOURCES`. Confirming it on the profile
    #: turns it into an answer ApplyFlow may give.
    NOT_CANDIDATE_ATTESTED = "not_candidate_attested"
    #: Stated, attested, and still does not settle *this* question — a visa
    #: holder asked about future sponsorship, an `OTHER` status. Answering
    #: would be guessing at a legal declaration.
    NOT_DERIVABLE = "not_derivable"


@dataclass(frozen=True)
class SensitiveFieldDecision:
    """Either an exact answer for a sensitive field, or a reason there is none.

    Never both, and never neither. A caller checks `is_answered` and is left
    with something to do in either branch: fill `answer`, or surface
    `refusal`.
    """

    answer: str | None = None
    refusal: SensitiveFieldRefusal | None = None

    def __post_init__(self) -> None:
        # Enforced rather than documented: a decision with neither set would
        # read as "no answer, no reason" and a caller would have nothing to
        # surface, while one with both set would let a filled answer travel
        # alongside a refusal to fill it.
        if (self.answer is None) == (self.refusal is None):
            raise InvalidValueError(
                "A SensitiveFieldDecision is exactly one of an answer or a "
                "refusal, never both and never neither."
            )
        if self.answer is not None and not self.answer.strip():
            raise InvalidValueError(
                "A SensitiveFieldDecision's answer cannot be blank — an empty "
                "string written into a legal field asserts nothing but looks "
                "answered."
            )

    @classmethod
    def answered(cls, answer: str) -> SensitiveFieldDecision:
        return cls(answer=answer)

    @classmethod
    def refused(cls, refusal: SensitiveFieldRefusal) -> SensitiveFieldDecision:
        return cls(refusal=refusal)

    @property
    def is_answered(self) -> bool:
        return self.answer is not None


def decide_sensitive_field(
    slot: ApplicationFieldSlot, *, profile: UserProfile
) -> SensitiveFieldDecision:
    """Decide what may go into the sensitive field `slot`, if anything.

    Raises `ValueError` for a slot that is not sensitive. That is a
    programming error, not a runtime condition: routing an ordinary field
    through the sensitive-field policy (or the reverse) would mean the two
    paths had been crossed, and failing loudly is how that gets caught in
    development rather than in a filled form.
    """
    if not is_sensitive_slot(slot):
        raise ValueError(
            f"'{slot.value}' is not a sensitive field; resolve it with "
            "resolve_profile_field instead."
        )

    # Checked before any data is read, so there is no code path on which EEO
    # data could influence the outcome.
    if requires_candidate_answer(slot):
        return SensitiveFieldDecision.refused(
            SensitiveFieldRefusal.CANDIDATE_CHOICE_ONLY
        )

    authorization = profile.work_authorization
    if authorization is None:
        return SensitiveFieldDecision.refused(SensitiveFieldRefusal.NOT_ON_FILE)
    if not authorization.is_candidate_attested:
        return SensitiveFieldDecision.refused(
            SensitiveFieldRefusal.NOT_CANDIDATE_ATTESTED
        )

    if slot is ApplicationFieldSlot.WORK_AUTHORIZATION:
        return _answer_authorized_to_work(authorization)
    if slot is ApplicationFieldSlot.SPONSORSHIP_REQUIRED:
        return _answer_requires_sponsorship(authorization)
    if slot is ApplicationFieldSlot.CITIZENSHIP_COUNTRY:
        return _answer_verbatim(authorization.citizenship_country)
    if slot is ApplicationFieldSlot.VISA_TYPE:
        return _answer_verbatim(authorization.visa_type)

    # Unreachable while every LEGAL_ATTESTATION slot is handled above, and a
    # refusal rather than a crash if a slot is ever added without a branch:
    # an unanswered sensitive field is a reviewable gap, a wrong one is not.
    return SensitiveFieldDecision.refused(SensitiveFieldRefusal.NOT_DERIVABLE)


def _answer_authorized_to_work(
    authorization: WorkAuthorization,
) -> SensitiveFieldDecision:
    """ "Are you legally authorized to work?" — from the stored status alone.

    `requires_sponsorship` is deliberately not consulted: needing a sponsor
    in future and being authorized today are different facts, and a candidate
    can truthfully answer yes to both.
    """
    if authorization.status in _AUTHORIZED_STATUSES:
        return SensitiveFieldDecision.answered(_YES)
    if authorization.status in _UNAUTHORIZED_STATUSES:
        return SensitiveFieldDecision.answered(_NO)
    return SensitiveFieldDecision.refused(SensitiveFieldRefusal.NOT_DERIVABLE)


def _answer_requires_sponsorship(
    authorization: WorkAuthorization,
) -> SensitiveFieldDecision:
    """ "Will you now or in the future require sponsorship?"

    The candidate's own explicit answer wins outright. Only when they left it
    unset does the status stand in, and only for the statuses that settle it
    on their own (see `_SPONSORSHIP_FROM_STATUS`).
    """
    if authorization.requires_sponsorship is not None:
        return SensitiveFieldDecision.answered(
            _YES if authorization.requires_sponsorship else _NO
        )

    derived = _SPONSORSHIP_FROM_STATUS.get(authorization.status)
    if derived is None:
        return SensitiveFieldDecision.refused(SensitiveFieldRefusal.NOT_DERIVABLE)
    return SensitiveFieldDecision.answered(derived)


def _answer_verbatim(value: str | None) -> SensitiveFieldDecision:
    """A stored free-text detail (citizenship country, visa type), exactly as
    the candidate wrote it. Blank counts as unstated — a whitespace-only
    value is not a declaration."""
    if value is None or not value.strip():
        return SensitiveFieldDecision.refused(SensitiveFieldRefusal.NOT_STATED)
    return SensitiveFieldDecision.answered(value.strip())
