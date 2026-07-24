"""ApplyUrlCheckerPort — an outbound port for probing whether a
`JobPosting`'s `apply_url` is still reachable.

Concrete implementations own the actual HTTP call and interpret its
result into a `LinkCheckOutcome` — this port never raises for the
network-level conditions it exists to detect (timeouts, connection
errors, DNS failures, 5xx, 404/410); those ARE the signal this port is
asked to produce, not a failure to obtain one, so they always come back
as a normal `LinkCheckOutcome` rather than an exception. This is a
deliberate departure from ports like `AtsBoardClientPort` (where a
network error means "we failed to learn the truth" and should degrade to
`None`) — here a network error, or lack of one, *is* evidence about the
target's own health, which `JobPosting.apply_link_check` weighs
accordingly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.value_objects.link_check_outcome import LinkCheckOutcome


class ApplyUrlCheckerPort(ABC):
    """Abstraction over a single apply-URL reachability probe."""

    @abstractmethod
    async def check(self, url: str) -> LinkCheckOutcome:
        """Probe `url` once and classify its reachability. Never raises
        for ordinary network/HTTP failures — see module docstring."""
