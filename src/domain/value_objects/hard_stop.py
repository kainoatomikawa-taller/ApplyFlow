"""HardStop — one detected boundary, with the evidence that detected it.

Evidence is required, not decorative. A hand-off interrupts what the
candidate asked for, so "we stopped, trust us" is not an acceptable thing to
show them: they have to be able to check the claim against the page they can
open in their own browser, and decide for themselves whether ApplyFlow read
it correctly. A `HardStop` with nothing to point at is therefore refused at
construction rather than rendered as an unexplained halt.

Evidence lines describe what matched on the *portal's* page — a vendor script
it loaded, a phrase it displayed, a field it presented. They never carry
anything about the candidate, which is what makes a `HardStop` safe to log,
return over the API, and store alongside the hand-off.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.hard_stop_kind import HardStopKind


@dataclass(frozen=True)
class HardStop:
    """A boundary found on a portal page, and why ApplyFlow thinks so."""

    kind: HardStopKind
    #: Short human-readable observations about the page, in the order they
    #: were found. Written for the candidate, not for a log parser.
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HardStopKind):
            raise InvalidValueError("HardStop requires a valid HardStopKind.")
        # A tuple, not any sequence: a list would be a mutable field on a
        # frozen value object, and this value gets stored and re-read.
        if not isinstance(self.evidence, tuple):
            raise InvalidValueError("HardStop.evidence must be a tuple.")
        if not self.evidence:
            raise InvalidValueError(
                "HardStop requires at least one piece of evidence — an "
                "unexplained hand-off is not something a candidate can check."
            )
        if any(not line.strip() for line in self.evidence):
            raise InvalidValueError("HardStop.evidence cannot contain blank lines.")

    @property
    def refusal_reason(self) -> str:
        return self.kind.refusal_reason

    @property
    def human_action(self) -> str:
        return self.kind.human_action
