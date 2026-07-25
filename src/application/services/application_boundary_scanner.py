"""scan_application_boundaries — asks a live browser session what is on the
page and asks the domain what it means.

Three lines of orchestration that are worth their own module because two
use cases must do this *identically*. The autofill pass checks for a
human-only boundary before it fills anything; the submit use case checks
again against the live page before it presses anything. If those two ever
drifted apart, the flow would either refuse to fill a form it would happily
submit or — much worse — submit past a check it had recognized minutes
earlier.

It holds no rules of its own. Which markers mean a CAPTCHA is
`detect_application_boundaries`' business, gathering them is the browser
adapter's, and this converts the domain's verdict into the DTO a caller
renders.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.application.dtos.application_autofill_dtos import ApplicationBoundaryOutput
from src.application.ports.browser_automation_port import BrowserSessionPort
from src.domain.services.application_boundary_detector import (
    detect_application_boundaries,
)
from src.domain.value_objects.application_boundary import ApplicationBoundary
from src.domain.value_objects.page_signals import PageSignals


async def scan_application_boundaries(
    session: BrowserSessionPort,
    *,
    field_labels: Sequence[str] = (),
    has_password_field: bool = False,
) -> tuple[ApplicationBoundary, ...]:
    """Every human-only check on the page `session` is parked on.

    The two field-derived signals are passed in rather than read here on
    purpose: reading the form would mint a new snapshot and invalidate the
    handles the caller is about to use. Callers hold a form read already —
    either the `FormField`s from the pass that filled it, or the review
    report describing them — so nothing is gained by re-reading and a
    working set of handles is lost.
    """
    return boundaries_in(
        await session.read_page_signals(),
        field_labels=field_labels,
        has_password_field=has_password_field,
    )


def boundaries_in(
    signals: PageSignals,
    *,
    field_labels: Sequence[str] = (),
    has_password_field: bool = False,
) -> tuple[ApplicationBoundary, ...]:
    """The same verdict, for a caller that already holds an observation.

    Exists so that a caller needing both the boundaries and the page's text
    — the submit use case, reading back what the portal answered with — takes
    one observation rather than two, without a second place that knows how
    to call the detector.
    """
    return detect_application_boundaries(
        signals, field_labels=field_labels, has_password_field=has_password_field
    )


def to_boundary_output(boundary: ApplicationBoundary) -> ApplicationBoundaryOutput:
    """Flatten one boundary into the DTO an interface layer renders."""
    return ApplicationBoundaryOutput(
        kind=boundary.kind.value,
        evidence=boundary.evidence,
        instruction=boundary.instruction,
        stopped_autofill=boundary.stops_autofill,
        blocks_submission=boundary.blocks_unattended_submit,
    )
