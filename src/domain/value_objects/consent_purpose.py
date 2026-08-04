"""ConsentPurpose — the things this application asks the user's permission for.

Why purposes and not one "I accept" flag
----------------------------------------
A single acceptance cannot be withdrawn in part, which means it cannot be
withdrawn in practice: a user who is happy for ApplyFlow to store their
applications but no longer wants their résumé sent to a model has, under a
single flag, exactly one option — delete everything. Purpose-specific consent
is what makes a partial "no" expressible, and GDPR Art. 6(1)(a) requires
consent to be given "for one or more specific purposes" for the same reason.

So the unit of consent here is the purpose, each one named after something the
user would recognize as a distinct thing the product does, and each one
carrying its own lawful basis (see `LawfulBasis`). Two of these purposes are
deliberately *not* consent-based, and saying so in the model is the point:
pretending the account itself runs on consent would mean offering a toggle
that cannot be honored.

Adding a purpose
----------------
A new purpose is a new thing the product does with personal data. It needs an
entry here, a basis in `_LAWFUL_BASES`, and — if it involves data this
application stores — a matching category in `PersonalDataInventory`. The
inventory is what export and erasure iterate over; this enum is what the user
is asked about. They are separate on purpose: not every purpose creates a new
store (the AI generation purpose creates none of its own), and not every store
is a purpose (an audit log is not something to ask permission for).

Values are stable strings: they are persisted in the consent ledger and appear
in URLs (`PUT /api/privacy/consents/{purpose}`), so renaming one is a
migration, not an edit.
"""

from __future__ import annotations

from enum import StrEnum

from src.domain.value_objects.lawful_basis import LawfulBasis


class ConsentPurpose(StrEnum):
    """One thing ApplyFlow does that the user is asked to agree to (or is told
    about, where consent is not the basis)."""

    #: Holding the profile, résumés, and application records that *are* the
    #: product. Contract, not consent: a job-application tracker that may not
    #: store applications is not a service anyone asked for. Listed anyway, so
    #: the user sees the complete picture of what is held and on what ground —
    #: and so the transparency obligation has somewhere to live.
    ACCOUNT_AND_APPLICATIONS = "account_and_applications"

    #: Sending résumé text, profile facts, and job descriptions to the model
    #: providers that draft tailored résumés and cover letters. Consent,
    #: because it is the one place personal data leaves this system for a
    #: third party in order to produce something optional.
    AI_DOCUMENT_GENERATION = "ai_document_generation"

    #: Keeping answers to application questions so a later application can
    #: reuse them (`answer_memories`). Consent: the reuse is a convenience,
    #: and the store is free-text the user wrote, which is why every column of
    #: that table is sensitive-flagged.
    ANSWER_REUSE = "answer_reuse"

    #: Storing citizenship, work authorization, and voluntary EEO
    #: self-identification. Explicit consent — GDPR Art. 9 special-category
    #: data, so a general acceptance does not reach it and it cannot be
    #: inferred from the user filling in an application.
    SENSITIVE_ATTRIBUTE_STORAGE = "sensitive_attribute_storage"

    #: Driving a browser over an employer's application portal on the user's
    #: behalf, which discloses their data to that employer. Consent, and worth
    #: its own toggle: a user may want tailored documents without ApplyFlow
    #: touching a real form.
    AUTOMATED_PORTAL_INTERACTION = "automated_portal_interaction"

    @property
    def lawful_basis(self) -> LawfulBasis:
        """The ground this purpose is processed on."""
        return _LAWFUL_BASES[self]

    @property
    def is_withdrawable(self) -> bool:
        """Whether the user can turn this off without deleting their account.

        False for `ACCOUNT_AND_APPLICATIONS`: withdrawing that is an erasure
        request, and the erasure path is where it is honored.
        """
        return self.lawful_basis.is_withdrawable

    @property
    def granted_by_default(self) -> bool:
        """Whether this purpose is permitted before the user has decided.

        Consent-based purposes start denied — an unanswered question is a "no".
        Contract-based ones start permitted, because the user asked for the
        service they are part of.
        """
        return self.lawful_basis.grants_by_default


_LAWFUL_BASES: dict[ConsentPurpose, LawfulBasis] = {
    ConsentPurpose.ACCOUNT_AND_APPLICATIONS: LawfulBasis.CONTRACT,
    ConsentPurpose.AI_DOCUMENT_GENERATION: LawfulBasis.CONSENT,
    ConsentPurpose.ANSWER_REUSE: LawfulBasis.CONSENT,
    ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE: LawfulBasis.EXPLICIT_CONSENT,
    ConsentPurpose.AUTOMATED_PORTAL_INTERACTION: LawfulBasis.CONSENT,
}
