"""Mapper between the ConsentRecord entity and its output DTOs.

Also the home of the user-facing description of each consent purpose. That text
is presentation, so it does not belong on `ConsentPurpose` — the domain enum
states the lawful basis and the withdrawal rule, which are rules, and stops
there. It lives in one place rather than in each caller because the consent
screen and the data export have to describe a purpose identically; two copies
would mean a user reading their export and a user reading the toggle were told
different things about the same processing.

A purpose with no description here fails loudly (`KeyError` at the mapping call
rather than a blank line in someone's export) — see `describe`, and the test that
asserts every enum member is covered.
"""

from __future__ import annotations

from src.application.dtos.data_rights_dtos import (
    ConsentDecisionOutput,
    ConsentStateOutput,
)
from src.domain.entities.consent_record import ConsentRecord
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose


class ConsentMapper:
    """Translates consent ledgers into output DTOs."""

    @staticmethod
    def to_state(record: ConsentRecord) -> ConsentStateOutput:
        current = record.current
        return ConsentStateOutput(
            purpose=record.purpose.value,
            description=ConsentMapper.describe(record.purpose),
            lawful_basis=record.purpose.lawful_basis.value,
            granted=record.is_granted,
            decided=record.has_been_decided,
            withdrawable=record.purpose.is_withdrawable,
            decided_at=current.decided_at if current else None,
            policy_version=record.policy_version,
        )

    @staticmethod
    def to_decision(decision: ConsentDecision) -> ConsentDecisionOutput:
        return ConsentDecisionOutput(
            purpose=decision.purpose.value,
            granted=decision.granted,
            decided_at=decision.decided_at,
            policy_version=decision.policy_version,
        )

    @staticmethod
    def describe(purpose: ConsentPurpose) -> str:
        """The user-facing description of `purpose`.

        Raises `KeyError` for a purpose with no text. Deliberately not a
        fallback to the enum value: a consent screen that asks the user to agree
        to `automated_portal_interaction` has not informed them of anything, and
        consent that is not informed is not consent. Adding a purpose therefore
        has to add its description.
        """
        return _PURPOSE_DESCRIPTIONS[purpose]


_PURPOSE_DESCRIPTIONS: dict[ConsentPurpose, str] = {
    ConsentPurpose.ACCOUNT_AND_APPLICATIONS: (
        "Storing your profile, résumés, and application records — what "
        "ApplyFlow is. Necessary to provide the service, so this is not "
        "something you can switch off; erasing your account is how to stop it."
    ),
    ConsentPurpose.AI_DOCUMENT_GENERATION: (
        "Sending your résumé text, profile facts, and the job description to "
        "AI providers so ApplyFlow can draft tailored résumés and cover "
        "letters."
    ),
    ConsentPurpose.ANSWER_REUSE: (
        "Keeping your answers to application questions so a later application "
        "can reuse them instead of asking you again."
    ),
    ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE: (
        "Storing your work authorization and citizenship, and any voluntary "
        "EEO self-identification you provided. ApplyFlow never fills EEO "
        "answers for you — see the review screen, where those stay yours to "
        "complete."
    ),
    ConsentPurpose.AUTOMATED_PORTAL_INTERACTION: (
        "Opening an employer's application portal on your behalf and filling "
        "the form, which discloses your data to that employer."
    ),
}
