"""Tests for InspectApplicationPortal — the gate every autofill capability
sits behind.

The central property is not "a hand-off is recorded" but *the form is never
read on a portal with a boundary*. A flow that read the fields and then
decided not to use them would already be holding a path to a login page's
password box, so the tests assert the ordering directly: `read_fields` is
never called, and the output carries nothing fillable.

The rest is about the hand-off being usable: one live hand-off per portal
rather than a pile of near-duplicates, the paused URL the candidate should
actually open, and a hand-off that clears itself when a later inspection finds
the wall gone.
"""

from __future__ import annotations

import pytest

from src.application.dtos.portal_handoff_dtos import InspectApplicationPortalInput
from src.application.exceptions import BrowserNavigationError
from src.application.ports.browser_automation_port import FormField, FormFieldKind
from src.application.use_cases.inspect_application_portal import (
    InspectApplicationPortal,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.portal_page_signals import PortalPageSignals
from tests.application.conftest import (
    InMemoryPortalHandoffRepository,
    ScriptedBrowserAutomation,
    SequentialIdGenerator,
    StubJobPostingRepository,
)

_APPLY_URL = "https://globex.example.com/apply/4242"

_CLEAN_SIGNALS = PortalPageSignals(
    url=_APPLY_URL,
    title="Senior Platform Engineer at Globex",
    text="Apply for this job. Attach your resume.",
    field_labels=("Full name", "Email"),
    fillable_field_count=2,
)

_CAPTCHA_SIGNALS = PortalPageSignals(
    url=_APPLY_URL,
    title="Senior Platform Engineer at Globex",
    text="Apply for this job. Verify you are human.",
    script_urls=("https://www.google.com/recaptcha/api.js",),
    field_labels=("Full name", "Email"),
    fillable_field_count=2,
)

_WALL_SIGNALS = PortalPageSignals(
    url="https://globex.example.com/login?next=/apply/4242",
    title="Sign in",
    text="Sign in to continue",
    field_labels=("Email", "Password"),
    password_field_count=1,
    fillable_field_count=2,
)

_CLEAN_FIELDS = (
    FormField(
        handle="g1-f0-0", kind=FormFieldKind.TEXT, label="Full name", name="name"
    ),
    FormField(
        handle="g1-f0-1",
        kind=FormFieldKind.EMAIL,
        label="Email",
        name="email",
        required=True,
    ),
)


def _posting() -> JobPosting:
    return JobPosting(
        id="job-1",
        source="greenhouse",
        company="Globex",
        title="Senior Platform Engineer",
        apply_url=_APPLY_URL,
        description="Platform role.",
    )


#: Distinguishes "the test did not care about the posting" from "the posting
#: does not exist", which is itself one of the cases under test.
_DEFAULT_POSTING = object()


def _use_case(
    *,
    harness: ScriptedBrowserAutomation,
    handoff_repository: InMemoryPortalHandoffRepository,
    posting: JobPosting | None | object = _DEFAULT_POSTING,
) -> InspectApplicationPortal:
    resolved = _posting() if posting is _DEFAULT_POSTING else posting
    return InspectApplicationPortal(
        job_posting_repository=StubJobPostingRepository(
            resolved  # type: ignore[arg-type]
        ),
        handoff_repository=handoff_repository,
        browser_automation=harness,
        id_generator=SequentialIdGenerator(prefix="handoff"),
    )


def _input() -> InspectApplicationPortalInput:
    return InspectApplicationPortalInput(user_id="user-1", job_posting_id="job-1")


# ---- a clean portal ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_portal_hands_back_its_questions(handoff_repository):
    harness = ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS)
    use_case = _use_case(harness=harness, handoff_repository=handoff_repository)

    output = await use_case.execute(_input())

    assert output.is_handed_off is False
    assert output.handoff is None
    assert [field.label for field in output.fields] == ["Full name", "Email"]
    assert output.fields[1].required is True
    assert handoff_repository.handoffs == {}


@pytest.mark.asyncio
async def test_the_portal_is_opened_at_the_postings_apply_url(handoff_repository):
    harness = ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS)

    await _use_case(harness=harness, handoff_repository=handoff_repository).execute(
        _input()
    )

    assert harness.opened == [_APPLY_URL]


@pytest.mark.asyncio
async def test_a_human_only_field_is_reported_rather_than_hidden(handoff_repository):
    """The two checks see different things — the field-level policy reads the
    `autocomplete` hint, which never reaches the page-level signals — so a
    credential box can survive a clean page reading. It comes back tagged, not
    silently dropped: a caller has to be able to see which question is off
    limits, and the harness refuses the write regardless.
    """
    masked = FormField(
        handle="g1-f0-2",
        kind=FormFieldKind.TEXT,
        label="Account access",
        name="access",
        attributes={"autocomplete": "current-password"},
        human_only_boundary=HardStopKind.ACCOUNT_WALL,
    )
    harness = ScriptedBrowserAutomation(
        signals=_CLEAN_SIGNALS, fields=(*_CLEAN_FIELDS, masked)
    )

    output = await _use_case(
        harness=harness, handoff_repository=handoff_repository
    ).execute(_input())

    assert output.is_handed_off is False
    reported = [field for field in output.fields if field.label == "Account access"]
    assert reported[0].human_only_boundary == HardStopKind.ACCOUNT_WALL.value


@pytest.mark.asyncio
async def test_returned_fields_carry_no_write_capability(handoff_repository):
    """Field handles only mean something inside the live session that minted
    them, and that session is closed by the time the caller sees this."""
    harness = ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS)

    output = await _use_case(
        harness=harness, handoff_repository=handoff_repository
    ).execute(_input())

    assert not any(hasattr(field, "handle") for field in output.fields)


# ---- a portal with a boundary ----------------------------------------------


@pytest.mark.asyncio
async def test_a_captcha_hands_off_and_the_form_is_never_read(handoff_repository):
    """The property the whole use case exists for: on a portal with a hard
    boundary the fields are not read at all, so there is nothing to fill even
    by accident."""
    harness = ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS, fields=_CLEAN_FIELDS)
    use_case = _use_case(harness=harness, handoff_repository=handoff_repository)

    output = await use_case.execute(_input())

    assert output.is_handed_off is True
    assert output.fields == []
    assert harness.sessions[0].read_fields_calls == 0
    assert harness.sessions[0].read_signals_calls == 1


@pytest.mark.asyncio
async def test_a_hand_off_is_stored_with_its_evidence_and_guidance(handoff_repository):
    harness = ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS)
    use_case = _use_case(harness=harness, handoff_repository=handoff_repository)

    output = await use_case.execute(_input())

    assert output.handoff is not None
    assert output.handoff.status == HandoffStatus.AWAITING_USER.value
    assert output.handoff.is_open is True
    stop = output.handoff.hard_stops[0]
    assert stop.kind == HardStopKind.CAPTCHA.value
    assert "never answers one" in stop.refusal_reason
    assert stop.human_action
    assert any("recaptcha" in line for line in stop.evidence)

    stored = handoff_repository.handoffs[output.handoff.id]
    assert stored.is_open is True
    assert stored.job_posting_id == "job-1"
    assert stored.user_id == "user-1"


@pytest.mark.asyncio
async def test_the_hand_off_points_at_the_url_automation_actually_landed_on(
    handoff_repository,
):
    """An apply link that redirects into a login flow has to send the
    candidate to the login page, not back to the link that redirected."""
    harness = ScriptedBrowserAutomation(signals=_WALL_SIGNALS)

    output = await _use_case(
        harness=harness, handoff_repository=handoff_repository
    ).execute(_input())

    assert output.handoff is not None
    assert output.handoff.apply_url == _APPLY_URL
    assert output.handoff.paused_url == _WALL_SIGNALS.url
    assert output.landed_url == _WALL_SIGNALS.url


@pytest.mark.asyncio
async def test_a_password_field_alone_is_enough_to_hand_off(handoff_repository):
    harness = ScriptedBrowserAutomation(signals=_WALL_SIGNALS, fields=_CLEAN_FIELDS)

    output = await _use_case(
        harness=harness, handoff_repository=handoff_repository
    ).execute(_input())

    assert output.is_handed_off is True
    assert output.handoff is not None
    assert [stop.kind for stop in output.handoff.hard_stops] == [
        HardStopKind.ACCOUNT_WALL.value
    ]


# ---- inspecting the same portal again --------------------------------------


@pytest.mark.asyncio
async def test_a_second_inspection_refreshes_the_same_hand_off(handoff_repository):
    """One live hand-off per portal. A new row per attempt would turn "what is
    waiting on me?" into a pile of near-duplicates."""
    first = ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS)
    output_one = await _use_case(
        harness=first, handoff_repository=handoff_repository
    ).execute(_input())

    second = ScriptedBrowserAutomation(signals=_WALL_SIGNALS)
    output_two = await _use_case(
        harness=second, handoff_repository=handoff_repository
    ).execute(_input())

    assert output_two.handoff is not None
    assert output_one.handoff is not None
    assert output_two.handoff.id == output_one.handoff.id
    assert len(handoff_repository.handoffs) == 1
    # The boundary changed between visits, and the record follows the page.
    assert [stop.kind for stop in output_two.handoff.hard_stops] == [
        HardStopKind.ACCOUNT_WALL.value
    ]
    assert output_two.handoff.created_at == output_one.handoff.created_at
    assert output_two.handoff.last_detected_at >= output_one.handoff.last_detected_at


@pytest.mark.asyncio
async def test_an_inspection_that_finds_no_boundary_clears_an_open_hand_off(
    handoff_repository,
):
    """The one case where ApplyFlow closes a hand-off on its own evidence: the
    wall the candidate was asked about is no longer there."""
    await _use_case(
        harness=ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS),
        handoff_repository=handoff_repository,
    ).execute(_input())
    raised_id = next(iter(handoff_repository.handoffs))

    output = await _use_case(
        harness=ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS),
        handoff_repository=handoff_repository,
    ).execute(_input())

    assert output.is_handed_off is False
    assert output.cleared_handoff_id == raised_id
    assert len(output.fields) == 2
    cleared = handoff_repository.handoffs[raised_id]
    assert cleared.status is HandoffStatus.RESUMED
    assert cleared.is_open is False
    assert "Cleared automatically" in cleared.resolution_note


@pytest.mark.asyncio
async def test_a_clean_portal_with_no_open_hand_off_clears_nothing(handoff_repository):
    output = await _use_case(
        harness=ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS),
        handoff_repository=handoff_repository,
    ).execute(_input())

    assert output.cleared_handoff_id is None


@pytest.mark.asyncio
async def test_another_candidates_open_hand_off_is_not_touched(handoff_repository):
    """Hand-offs are per candidate: one person's unresolved wall must not be
    resolved by somebody else's inspection of the same posting."""
    await _use_case(
        harness=ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS),
        handoff_repository=handoff_repository,
    ).execute(InspectApplicationPortalInput(user_id="user-2", job_posting_id="job-1"))

    output = await _use_case(
        harness=ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS),
        handoff_repository=handoff_repository,
    ).execute(_input())

    assert output.cleared_handoff_id is None
    assert all(handoff.is_open for handoff in handoff_repository.handoffs.values())


# ---- failures ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_posting_never_opens_a_browser(handoff_repository):
    harness = ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS)
    use_case = _use_case(
        harness=harness, handoff_repository=handoff_repository, posting=None
    )

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(_input())

    assert harness.opened == []


@pytest.mark.asyncio
async def test_a_portal_that_will_not_load_raises_and_records_nothing(
    handoff_repository,
):
    """A dead apply link is not a hand-off: there is no boundary and nothing
    for the candidate to do about it."""
    harness = ScriptedBrowserAutomation(
        signals=_CLEAN_SIGNALS,
        open_error=BrowserNavigationError(_APPLY_URL, "it timed out"),
    )

    with pytest.raises(BrowserNavigationError):
        await _use_case(harness=harness, handoff_repository=handoff_repository).execute(
            _input()
        )

    assert handoff_repository.handoffs == {}


@pytest.mark.asyncio
async def test_the_session_is_closed_even_when_the_reading_fails(handoff_repository):
    """A browser context leaked per inspection is how a worker runs out of
    memory a few hundred applications later."""
    harness = ScriptedBrowserAutomation(
        signals=_CLEAN_SIGNALS, signals_error=RuntimeError("the page crashed")
    )

    with pytest.raises(RuntimeError):
        await _use_case(harness=harness, handoff_repository=handoff_repository).execute(
            _input()
        )

    assert harness.sessions[0].closed is True


@pytest.mark.asyncio
async def test_the_session_is_closed_on_a_clean_portal_and_on_a_hand_off(
    handoff_repository,
):
    clean = ScriptedBrowserAutomation(signals=_CLEAN_SIGNALS, fields=_CLEAN_FIELDS)
    await _use_case(harness=clean, handoff_repository=handoff_repository).execute(
        _input()
    )

    walled = ScriptedBrowserAutomation(signals=_CAPTCHA_SIGNALS)
    await _use_case(harness=walled, handoff_repository=handoff_repository).execute(
        _input()
    )

    assert clean.sessions[0].closed is True
    assert walled.sessions[0].closed is True
