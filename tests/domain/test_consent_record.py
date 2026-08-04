"""Tests for the consent ledger: purposes, decisions, and the record that
aggregates them.

The behaviour worth pinning down is not "a boolean round-trips". It is the four
rules that make the ledger usable as the GDPR Art. 7(1) demonstration record: an
unanswered purpose has a defined answer, a withdrawal is impossible where it
cannot be honored, the tail always means "current", and a restatement is not an
event.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.consent_record import ConsentRecord
from src.domain.exceptions import (
    ConsentLedgerOutOfOrderError,
    ConsentNotWithdrawableError,
    InvalidValueError,
)
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose
from src.domain.value_objects.lawful_basis import LawfulBasis

_AT = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_POLICY = "2026-08-03"


def _decision(
    purpose: ConsentPurpose = ConsentPurpose.ANSWER_REUSE,
    *,
    granted: bool = True,
    at: datetime = _AT,
    policy_version: str = _POLICY,
) -> ConsentDecision:
    return ConsentDecision(
        purpose=purpose,
        granted=granted,
        decided_at=at,
        policy_version=policy_version,
    )


# -- Lawful basis and purpose defaults ---------------------------------------


def test_consent_based_purposes_start_denied_and_contract_ones_start_granted() -> None:
    """The opt-in rule, expressed once. An unanswered consent question is a
    "no"; processing the user asked for by using the product is not."""
    assert not ConsentPurpose.ANSWER_REUSE.granted_by_default
    assert not ConsentPurpose.AI_DOCUMENT_GENERATION.granted_by_default
    assert not ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE.granted_by_default
    assert ConsentPurpose.ACCOUNT_AND_APPLICATIONS.granted_by_default


def test_only_consent_based_purposes_are_withdrawable() -> None:
    assert ConsentPurpose.ANSWER_REUSE.is_withdrawable
    assert ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE.is_withdrawable
    assert not ConsentPurpose.ACCOUNT_AND_APPLICATIONS.is_withdrawable


def test_special_category_storage_needs_explicit_consent() -> None:
    """Art. 9 data cannot ride on a general acceptance. Recorded as a distinct
    basis so the distinction survives into an audit."""
    assert (
        ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE.lawful_basis
        is LawfulBasis.EXPLICIT_CONSENT
    )


def test_every_purpose_declares_a_lawful_basis() -> None:
    """A purpose with no basis would fall through to a `KeyError` at the first
    read. Asserted over the enum so adding a member forces the decision."""
    for purpose in ConsentPurpose:
        assert isinstance(purpose.lawful_basis, LawfulBasis)


# -- ConsentDecision ---------------------------------------------------------


def test_withdrawing_a_contract_based_purpose_is_refused_at_construction() -> None:
    """The refusal is in the value object, not the endpoint, so no path — API,
    CLI, task or test — can put an unhonorable withdrawal in the ledger. A
    record claiming the user switched off something the application never stops
    doing is a false record of compliance."""
    with pytest.raises(ConsentNotWithdrawableError):
        _decision(ConsentPurpose.ACCOUNT_AND_APPLICATIONS, granted=False)


def test_granting_a_contract_based_purpose_is_allowed() -> None:
    """Affirming it is fine and meaningful — it is the acceptance of the notice.
    Only the withdrawal is impossible."""
    assert _decision(ConsentPurpose.ACCOUNT_AND_APPLICATIONS, granted=True).granted


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        _decision(at=datetime(2026, 8, 3, 12, 0))


def test_a_decision_needs_a_policy_version() -> None:
    """Consent with no record of what the user was told cannot be shown to have
    been informed, which is half of what makes it consent."""
    with pytest.raises(InvalidValueError):
        _decision(policy_version="   ")


def test_a_restatement_compares_the_answer_and_the_notice_but_not_the_clock() -> None:
    first = _decision()
    assert first.restates(_decision(at=_AT + timedelta(days=1)))
    # A new notice version is never a restatement: re-consent after a changed
    # notice is exactly the event the ledger exists to capture.
    assert not first.restates(_decision(policy_version="2027-01-01"))
    assert not first.restates(_decision(granted=False))


# -- ConsentRecord -----------------------------------------------------------


def test_an_empty_ledger_answers_from_the_purpose_default() -> None:
    """ "Never asked" is a state with a definite answer, not an unknown — which
    is why the repository returns a record rather than None."""
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    assert not record.is_granted
    assert not record.has_been_decided
    assert record.current is None
    assert record.policy_version is None


def test_granted_reads_the_tail_of_the_ledger() -> None:
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    record.record(_decision())
    assert record.is_granted
    record.record(_decision(granted=False, at=_AT + timedelta(hours=1)))
    assert not record.is_granted
    # Both decisions survive: the withdrawal does not erase the grant, which is
    # the whole reason this is a ledger.
    assert len(record.history) == 2
    assert record.has_been_decided


def test_recording_a_restatement_appends_nothing_and_reports_no_change() -> None:
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    assert record.record(_decision()) is True
    assert record.record(_decision(at=_AT + timedelta(minutes=5))) is False
    assert len(record.history) == 1


def test_re_consent_under_a_new_notice_version_is_a_new_entry() -> None:
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    record.record(_decision())
    assert (
        record.record(
            _decision(at=_AT + timedelta(days=30), policy_version="2027-01-01")
        )
        is True
    )
    assert record.policy_version == "2027-01-01"


def test_a_decision_dated_before_the_current_one_is_refused() -> None:
    """The tail has to mean "current". An out-of-order entry would make "is this
    granted?" depend on insertion order rather than on what the user decided."""
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    record.record(_decision())
    with pytest.raises(ConsentLedgerOutOfOrderError):
        record.record(_decision(granted=False, at=_AT - timedelta(hours=1)))


def test_a_decision_about_another_purpose_is_refused() -> None:
    record = ConsentRecord(user_id="u1", purpose=ConsentPurpose.ANSWER_REUSE)
    with pytest.raises(InvalidValueError):
        record.record(_decision(ConsentPurpose.AI_DOCUMENT_GENERATION))


def test_a_stored_history_is_validated_on_load_not_only_on_append() -> None:
    """A repository assembling a ledger from rows is held to the same rule as
    code building one in memory — a stored ledger out of order would otherwise
    read as a different answer than the user gave."""
    with pytest.raises(ConsentLedgerOutOfOrderError):
        ConsentRecord(
            user_id="u1",
            purpose=ConsentPurpose.ANSWER_REUSE,
            history=(
                _decision(at=_AT),
                _decision(granted=False, at=_AT - timedelta(days=1)),
            ),
        )


def test_a_record_requires_a_user_id() -> None:
    with pytest.raises(InvalidValueError):
        ConsentRecord(user_id="  ", purpose=ConsentPurpose.ANSWER_REUSE)
