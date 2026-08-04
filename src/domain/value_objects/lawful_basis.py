"""LawfulBasis — why this application is allowed to hold a piece of personal
data at all.

Every category in the personal-data inventory and every consent purpose names
one of these. That is not decoration: the basis decides three things the rest
of the data-rights machinery reads off it rather than hard-coding.

1. **Whether the user can say no.** Consent is withdrawable by definition
   (GDPR Art. 7(3)); contract and legal obligation are not. A UI that offers a
   toggle for something the application cannot actually stop doing is worse
   than no toggle, so `is_withdrawable` is what decides whether one is shown —
   and `ConsentDecision` refuses to record a withdrawal against a basis that
   has none.
2. **What the default is before anyone has been asked.** Consent-based
   processing is off until it is granted (opt-in, Art. 4(11) — "a clear
   affirmative action"). Contract-based processing is on, because the user
   asked for the service. `grants_by_default` is that rule in one place.
3. **What has to happen on erasure.** A category held under a legal obligation
   survives an erasure request; one held under consent does not. See
   `ErasureDisposition`, which pairs with this.

`EXPLICIT_CONSENT` is separate from `CONSENT` because Art. 9 special-category
data (this application stores work authorization, citizenship, and voluntary
EEO self-identification) needs a higher bar than ordinary consent: it cannot
be bundled into a general acceptance, and it cannot be inferred from use of
the product. Both are withdrawable and both are opt-in, so nothing in the code
branches on the difference today — it is recorded because the distinction is
the thing an auditor asks about, and reconstructing it later from a boolean is
not possible.

CCPA/CPRA has no lawful-basis concept; it works from notice-at-collection plus
a right to opt out of "sale/sharing". This enum still carries what that regime
needs, because the categories it labels are the same categories a
notice-at-collection has to enumerate. See
docs/decisions/0004-gdpr-ccpa-groundwork.md.
"""

from __future__ import annotations

from enum import StrEnum


class LawfulBasis(StrEnum):
    """The ground on which a piece of personal data is processed."""

    #: The user opted in and may opt out at any time (GDPR Art. 6(1)(a)).
    CONSENT = "consent"

    #: Opt-in for special-category data (Art. 9(2)(a)) — citizenship, work
    #: authorization, EEO self-identification. Same mechanics as `CONSENT`,
    #: recorded separately because the standard of consent is higher.
    EXPLICIT_CONSENT = "explicit_consent"

    #: Necessary to deliver what the user asked for (Art. 6(1)(b)). Not
    #: withdrawable in isolation: withdrawing it means closing the account,
    #: which is what the erasure path is for.
    CONTRACT = "contract"

    #: Necessary for a legitimate interest that does not override the user's
    #: rights (Art. 6(1)(f)) — in this codebase, keeping a service operable
    #: and auditable rather than anything that profiles the user.
    LEGITIMATE_INTEREST = "legitimate_interest"

    #: Required by law to be kept (Art. 6(1)(c)) — the one basis that survives
    #: an erasure request, and the reason `ErasureDisposition` has a
    #: `RETAIN_LEGAL_BASIS` member at all.
    LEGAL_OBLIGATION = "legal_obligation"

    @property
    def is_consent_based(self) -> bool:
        """Whether the user's agreement is what makes this processing lawful."""
        return self in _CONSENT_BASED

    @property
    def is_withdrawable(self) -> bool:
        """Whether the user can stop this processing without closing the
        account. True for exactly the consent-based bases."""
        return self.is_consent_based

    @property
    def grants_by_default(self) -> bool:
        """Whether processing may proceed before the user has decided anything.

        False for consent — an unanswered consent question is a "no", never a
        "not yet objected". True for the others, whose lawfulness does not come
        from an answer the user gives.
        """
        return not self.is_consent_based


_CONSENT_BASED: frozenset[LawfulBasis] = frozenset(
    {LawfulBasis.CONSENT, LawfulBasis.EXPLICIT_CONSENT}
)
