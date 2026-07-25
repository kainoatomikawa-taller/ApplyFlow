"""Mapper between PortalHandoff / FormField and their output DTOs."""

from __future__ import annotations

from datetime import datetime

from src.application.dtos.portal_handoff_dtos import (
    HardStopOutput,
    PortalFieldOutput,
    PortalHandoffOutput,
)
from src.application.ports.browser_automation_port import FormField
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.value_objects.hard_stop import HardStop


class PortalHandoffMapper:
    """Translates hand-offs and discovered fields into output DTOs.

    `user_id` is never mapped out: every read is already scoped to the
    requesting candidate by the use case, so echoing the id back would only
    widen what a response carries.

    Field handles are never mapped out either, and that one is a rule rather
    than a tidiness preference — a handle only means anything inside the live
    browser session that minted it, so carrying one into a response would be
    offering a write capability that expired before the response was sent.
    """

    @staticmethod
    def to_output(handoff: PortalHandoff) -> PortalHandoffOutput:
        return PortalHandoffOutput(
            id=handoff.id,
            job_posting_id=handoff.job_posting_id,
            apply_url=handoff.apply_url,
            paused_url=handoff.paused_url,
            status=handoff.status.value,
            is_open=handoff.is_open,
            created_at=handoff.created_at,
            # Always set by the entity — see `PortalHandoff.__post_init__`,
            # which defaults it to `created_at` rather than leaving it None.
            last_detected_at=_required(handoff.last_detected_at, handoff.created_at),
            resolved_at=handoff.resolved_at,
            resolution_note=handoff.resolution_note,
            hard_stops=[
                PortalHandoffMapper.hard_stop_to_output(stop)
                for stop in handoff.hard_stops
            ],
        )

    @staticmethod
    def hard_stop_to_output(hard_stop: HardStop) -> HardStopOutput:
        return HardStopOutput(
            kind=hard_stop.kind.value,
            refusal_reason=hard_stop.refusal_reason,
            human_action=hard_stop.human_action,
            evidence=list(hard_stop.evidence),
        )

    @staticmethod
    def field_to_output(form_field: FormField) -> PortalFieldOutput:
        boundary = form_field.human_only_boundary
        return PortalFieldOutput(
            label=form_field.label,
            kind=form_field.kind.value,
            name=form_field.name,
            required=form_field.required,
            human_only_boundary=boundary.value if boundary is not None else None,
        )


def _required(value: datetime | None, fallback: datetime) -> datetime:
    return value if value is not None else fallback
