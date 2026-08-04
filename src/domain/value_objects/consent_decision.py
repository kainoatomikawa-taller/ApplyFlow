"""ConsentDecision — one recorded answer to one consent question.

Why the ledger is decisions and not a boolean per purpose
---------------------------------------------------------
GDPR Art. 7(1) puts the burden of proof on the controller: it must be able to
*demonstrate* that consent was given. A boolean column cannot demonstrate
anything — it says what the answer is now, not that it was ever given, when, or
against which version of the notice the user read. A withdrawal is even worse
served by a boolean, because the fact that matters afterwards ("processing
stopped on the 14th") is exactly the fact the overwrite destroys.

So consent is an append-only ledger of these, and the current state is the last
entry (see `ConsentRecord`). Same shape and same reasoning as
`ApplicationStatusChange`: a decision is something that happened, so it is
frozen, it has no identity of its own, and nothing edits one.

`policy_version` is the part people leave out and then need. Consent is only
valid for what the user was actually told, so a materially changed privacy
notice invalidates consent collected under the old one. Recording the version
each decision was made against is what makes "who still needs to be re-asked?"
answerable without guesswork.

Not sensitive in the encrypt-at-rest sense. A purpose, a yes/no, a timestamp
and a version string describe a *decision about* personal data without
containing any — which is what lets the ledger be queried, aggregated, and
(see `ErasureDisposition.RETAIN_LEGAL_BASIS`) retained past an erasure request
as the demonstration record Art. 7(1) asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from src.domain.exceptions import ConsentNotWithdrawableError, InvalidValueError
from src.domain.value_objects.consent_purpose import ConsentPurpose


@dataclass(frozen=True)
class ConsentDecision:
    """The user's answer to one consent question, at one moment."""

    #: Long enough for a date-stamped or semantic version, short enough to
    #: stay an identifier rather than becoming a place to store prose.
    MAX_POLICY_VERSION_LENGTH: ClassVar[int] = 32

    #: What was decided about.
    purpose: ConsentPurpose
    #: True for "yes, do this", False for a withdrawal. A withdrawal is only
    #: constructible for a purpose whose basis is consent — see `__post_init__`.
    granted: bool
    #: When the user decided. Timezone-aware, for the same reason every other
    #: timestamp in this domain is: a ledger that has to order correctly is a
    #: ledger that cannot afford a naive datetime.
    decided_at: datetime
    #: The privacy-notice version the decision was made against. Required:
    #: consent with no record of what was disclosed cannot be demonstrated to
    #: have been informed, which is half of what makes it consent.
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, ConsentPurpose):
            raise InvalidValueError("ConsentDecision requires a valid ConsentPurpose.")
        if self.decided_at.tzinfo is None:
            raise InvalidValueError(
                "ConsentDecision.decided_at must be timezone-aware so a "
                "consent ledger orders correctly across regions."
            )
        version = self.policy_version.strip()
        if not version:
            raise InvalidValueError(
                "ConsentDecision.policy_version is required: a decision with "
                "no record of what the user was told cannot be shown to have "
                "been informed."
            )
        if len(version) > ConsentDecision.MAX_POLICY_VERSION_LENGTH:
            raise InvalidValueError(
                "ConsentDecision.policy_version cannot exceed "
                f"{ConsentDecision.MAX_POLICY_VERSION_LENGTH} characters."
            )
        # Refused at construction rather than at the repository or the
        # endpoint, so there is no path — API, CLI, task, or test — that can
        # put an unhonorable withdrawal in the ledger. A ledger entry saying
        # the user turned off something the application never stops doing
        # would be a false record of compliance, which is worse than no record.
        if not self.granted and not self.purpose.is_withdrawable:
            raise ConsentNotWithdrawableError(self.purpose.value)

    @property
    def is_withdrawal(self) -> bool:
        return not self.granted

    def restates(self, other: ConsentDecision) -> bool:
        """Whether this decision says exactly what `other` already said.

        Compares the purpose, the answer, and the policy version — but not the
        timestamp, which is what makes this the "nothing changed" test rather
        than an equality check. `ConsentRecord` uses it to keep a re-submitted
        toggle from appending an entry that adds no information; a decision
        made against a *new* policy version is never a restatement, because
        re-consent under a new notice is a real event.
        """
        return (
            self.purpose is other.purpose
            and self.granted == other.granted
            and self.policy_version.strip() == other.policy_version.strip()
        )
