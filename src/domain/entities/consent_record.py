"""ConsentRecord — one user's consent history for one purpose.

The aggregate is (user, purpose), and what it holds is a ledger rather than a
state. `is_granted` is derived from the last entry; nothing sets it. That is the
whole design, and it is what makes the two questions consent has to answer
answerable at once: "may we do this right now?" reads the tail, and "can you
demonstrate the user agreed, and when, and to what?" reads the whole thing
(GDPR Art. 7(1)).

The empty record is meaningful, not a missing one
------------------------------------------------
A user who has never been asked has an empty history, and that is a real state
with a real answer: consent-based purposes are denied, contract-based ones are
permitted (see `ConsentPurpose.granted_by_default`). Modelling the absence of a
row as "unknown" would push that decision out to every caller, and the callers
that forgot would default to permitting — which is precisely the failure the
opt-in rule exists to prevent. So the repository returns a `ConsentRecord` with
an empty history rather than `None`, and there is no code path where "not
asked" has to be handled separately from "said no".

Append-only, and refuses two things
-----------------------------------
`record()` appends; nothing edits or removes an entry, because a decision is
something that happened. It refuses a decision dated before the one it follows
(the tail would stop meaning "current"), and it declines to append a decision
that restates the current one verbatim — a re-submitted toggle is not a new
event, and a ledger of identical rows is a ledger nobody can read. A decision
under a *new* policy version is never a restatement: re-consent after a changed
notice is exactly the event this ledger exists to capture.

Withdrawal of a non-consent purpose is refused too, but further in — by
`ConsentDecision` itself, so no path can construct one to hand here.
"""

from __future__ import annotations

from src.domain.exceptions import ConsentLedgerOutOfOrderError, InvalidValueError
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose


class ConsentRecord:
    """The consent ledger for one (user, purpose) pair."""

    def __init__(
        self,
        *,
        user_id: str,
        purpose: ConsentPurpose,
        history: tuple[ConsentDecision, ...] = (),
    ) -> None:
        if not user_id.strip():
            raise InvalidValueError("ConsentRecord.user_id is required.")
        if not isinstance(purpose, ConsentPurpose):
            raise InvalidValueError("ConsentRecord requires a ConsentPurpose.")
        self._user_id = user_id
        self._purpose = purpose
        self._history = tuple(history)
        self._validate_history()

    def _validate_history(self) -> None:
        """Reject a ledger that cannot mean what a ledger means.

        Runs on load as well as on append, so a history assembled by a
        repository from rows written years apart is held to the same rule as
        one built in memory — a stored ledger out of order would otherwise read
        as a different answer than the one the user gave.
        """
        for decision in self._history:
            if decision.purpose is not self._purpose:
                raise InvalidValueError(
                    f"ConsentRecord for '{self._purpose.value}' was given a "
                    f"decision about '{decision.purpose.value}'."
                )
        for earlier, later in zip(self._history, self._history[1:], strict=False):
            if later.decided_at < earlier.decided_at:
                raise ConsentLedgerOutOfOrderError(self._purpose.value)

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def purpose(self) -> ConsentPurpose:
        return self._purpose

    @property
    def history(self) -> tuple[ConsentDecision, ...]:
        """Every decision, oldest first. The demonstration record."""
        return self._history

    @property
    def current(self) -> ConsentDecision | None:
        """The decision in effect, or None if the user has never been asked."""
        return self._history[-1] if self._history else None

    @property
    def is_granted(self) -> bool:
        """Whether this purpose may be acted on right now.

        The tail of the ledger, or the purpose's default when the ledger is
        empty. This is the only question the runtime should ask; nothing should
        read `history` to decide whether to proceed.
        """
        current = self.current
        if current is None:
            return self._purpose.granted_by_default
        return current.granted

    @property
    def has_been_decided(self) -> bool:
        """Whether the user has answered at all — which is a different question
        from whether the answer was yes. What a "you still need to ask them"
        prompt reads."""
        return bool(self._history)

    @property
    def policy_version(self) -> str | None:
        """The notice version the current decision was made against, or None if
        there is none. What tells you whether a changed privacy notice has
        invalidated this consent and the user has to be re-asked."""
        current = self.current
        return current.policy_version if current else None

    def record(self, decision: ConsentDecision) -> bool:
        """Append `decision`, unless it says nothing new.

        Returns whether the ledger changed, so a caller can report "already in
        that state" without having to compare before and after. The no-op case
        is the common one in practice — a client re-sending the state of a
        toggle it already rendered — and appending for it would fill the
        demonstration record with rows that demonstrate nothing.

        Raises:
            InvalidValueError: if the decision is about a different purpose.
            ConsentLedgerOutOfOrderError: if it predates the current decision.
        """
        if decision.purpose is not self._purpose:
            raise InvalidValueError(
                f"Cannot record a '{decision.purpose.value}' decision on the "
                f"ledger for '{self._purpose.value}'."
            )
        current = self.current
        if current is not None:
            if decision.decided_at < current.decided_at:
                raise ConsentLedgerOutOfOrderError(self._purpose.value)
            if decision.restates(current):
                return False
        self._history = (*self._history, decision)
        return True
