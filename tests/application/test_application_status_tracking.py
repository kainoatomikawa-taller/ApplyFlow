"""Use case tests for application status tracking.

The properties worth holding onto here are the ones a controller could
plausibly get wrong on its own:

- a status arrives as a string, and only the use case decides whether it names a
  status. `draft` is a string that parses and still has to be refused.
- ownership is checked, and a miss looks the same as a genuinely missing id —
  otherwise the status route becomes a way to probe for other candidates' work.
- an update persists, once, and the persisted application carries the history.
- filtering happens in the repository call, not over the results, so a test that
  asserted only on the returned list would pass against an implementation that
  fetched everything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.tracked_application_dtos import (
    GetTrackedApplicationInput,
    ListApplicationsForJobInput,
    ListTrackedApplicationsInput,
    UpdateApplicationStatusInput,
)
from src.application.use_cases.get_tracked_application import GetTrackedApplication
from src.application.use_cases.list_applications_for_job import ListApplicationsForJob
from src.application.use_cases.list_tracked_applications import ListTrackedApplications
from src.application.use_cases.update_application_status import UpdateApplicationStatus
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.domain.value_objects.application_status import ApplicationStatus
from tests.application.conftest import InMemoryTrackedApplicationRepository

_USER = "user-1"
_OTHER_USER = "user-2"
_APPLIED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


def _application(
    application_id: str = "app-1",
    *,
    user_id: str = _USER,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    job_posting_id: str = "job-1",
    applied_at: datetime = _APPLIED_AT,
) -> TrackedApplication:
    return TrackedApplication(
        id=application_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        submission_key=f"review-{application_id}",
        company_name="Globex",
        role_title="Senior Backend Engineer",
        applied_at=applied_at,
        resume_document_id="doc-resume",
        status=status,
    )


def _repository(
    *applications: TrackedApplication,
) -> InMemoryTrackedApplicationRepository:
    return InMemoryTrackedApplicationRepository(list(applications))


# ---- updating a status ------------------------------------------------------


async def test_a_status_update_moves_the_application_and_records_the_move() -> None:
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    output = await use_case.execute(
        UpdateApplicationStatusInput(
            user_id=_USER,
            application_id="app-1",
            status="interviewing",
            note="recruiter screen on the 14th",
        )
    )

    assert output.status == "interviewing"
    assert output.is_open
    assert [entry.status for entry in output.status_history] == [
        "applied",
        "interviewing",
    ]
    latest = output.status_history[-1]
    assert latest.previous_status == "applied"
    assert latest.note == "recruiter screen on the 14th"


async def test_a_status_update_persists_through_the_repository() -> None:
    """The acceptance criterion that the update survives the request — asserted
    against what the store holds, not against the returned DTO."""
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    await use_case.execute(
        UpdateApplicationStatusInput(
            user_id=_USER, application_id="app-1", status="interviewing"
        )
    )

    assert repository.update_calls == 1
    stored = repository.rows["app-1"]
    assert stored.status is ApplicationStatus.INTERVIEWING
    assert len(stored.status_history) == 2


async def test_successive_updates_build_up_the_history() -> None:
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    for target in ("interviewing", "offer", "rejected"):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status=target
            )
        )

    stored = repository.rows["app-1"]
    assert [entry.status.value for entry in stored.status_history] == [
        "applied",
        "interviewing",
        "offer",
        "rejected",
    ]
    assert not stored.is_open
    assert stored.has_held_status(ApplicationStatus.OFFER)


async def test_current_status_since_reports_when_it_last_moved() -> None:
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    output = await use_case.execute(
        UpdateApplicationStatusInput(
            user_id=_USER, application_id="app-1", status="interviewing"
        )
    )

    assert output.current_status_since > output.applied_at
    assert output.current_status_since == output.status_history[-1].changed_at


async def test_an_illegal_transition_is_refused_by_the_domain() -> None:
    repository = _repository(_application(status=ApplicationStatus.REJECTED))
    use_case = UpdateApplicationStatus(repository=repository)

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status="interviewing"
            )
        )

    assert repository.update_calls == 0
    assert repository.rows["app-1"].status is ApplicationStatus.REJECTED


async def test_repeating_the_same_status_is_refused() -> None:
    """What makes the route safe to retry: a second identical request cannot
    append a duplicate step."""
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status="applied"
            )
        )

    assert len(repository.rows["app-1"].status_history) == 1


async def test_a_status_that_is_not_a_status_is_refused_before_any_read() -> None:
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    with pytest.raises(InvalidValueError, match="is not an application status"):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status="ghosted"
            )
        )

    assert repository.update_calls == 0


async def test_moving_a_sent_application_back_to_draft_is_refused() -> None:
    """`draft` parses as a status, so the guard has to be explicit — and the
    message says where a draft actually lives."""
    repository = _repository(_application())
    use_case = UpdateApplicationStatus(repository=repository)

    with pytest.raises(InvalidValueError, match="ApplicationReview"):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status="draft"
            )
        )


async def test_updating_an_unknown_application_is_not_found() -> None:
    use_case = UpdateApplicationStatus(repository=_repository())

    with pytest.raises(TrackedApplicationNotFoundError):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="nope", status="interviewing"
            )
        )


async def test_updating_another_candidates_application_is_not_found() -> None:
    """Not "forbidden": distinguishing the two would confirm that an
    application exists under an id someone guessed."""
    repository = _repository(_application(user_id=_OTHER_USER))
    use_case = UpdateApplicationStatus(repository=repository)

    with pytest.raises(TrackedApplicationNotFoundError):
        await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=_USER, application_id="app-1", status="interviewing"
            )
        )

    assert repository.update_calls == 0
    assert repository.rows["app-1"].status is ApplicationStatus.APPLIED


# ---- reading one application -----------------------------------------------


async def test_reading_an_application_returns_its_history() -> None:
    application = _application()
    application.change_status(ApplicationStatus.INTERVIEWING)
    use_case = GetTrackedApplication(repository=_repository(application))

    output = await use_case.execute(
        GetTrackedApplicationInput(user_id=_USER, application_id="app-1")
    )

    assert output.status == "interviewing"
    assert len(output.status_history) == 2


async def test_reading_another_candidates_application_is_not_found() -> None:
    use_case = GetTrackedApplication(
        repository=_repository(_application(user_id=_OTHER_USER))
    )

    with pytest.raises(TrackedApplicationNotFoundError):
        await use_case.execute(
            GetTrackedApplicationInput(user_id=_USER, application_id="app-1")
        )


# ---- listing and filtering -------------------------------------------------


async def test_the_feed_returns_a_candidates_applications_newest_first() -> None:
    repository = _repository(
        _application("older", applied_at=_APPLIED_AT),
        _application("newer", applied_at=_APPLIED_AT + timedelta(days=5)),
        _application("theirs", user_id=_OTHER_USER),
    )
    use_case = ListTrackedApplications(repository=repository)

    outputs = await use_case.execute(ListTrackedApplicationsInput(user_id=_USER))

    assert [output.id for output in outputs] == ["newer", "older"]


async def test_the_feed_can_be_filtered_to_named_statuses() -> None:
    repository = _repository(
        _application("a", status=ApplicationStatus.APPLIED),
        _application("b", status=ApplicationStatus.INTERVIEWING),
        _application("c", status=ApplicationStatus.REJECTED),
    )
    use_case = ListTrackedApplications(repository=repository)

    outputs = await use_case.execute(
        ListTrackedApplicationsInput(
            user_id=_USER, statuses=("interviewing", "rejected")
        )
    )

    assert {output.id for output in outputs} == {"b", "c"}


async def test_open_only_is_resolved_from_the_domains_terminal_rule() -> None:
    """Not from a list of "live" statuses kept in the application layer, which
    could fall out of step with the lifecycle."""
    repository = _repository(
        _application("applied", status=ApplicationStatus.APPLIED),
        _application("interviewing", status=ApplicationStatus.INTERVIEWING),
        _application("offer", status=ApplicationStatus.OFFER),
        _application("rejected", status=ApplicationStatus.REJECTED),
        _application("withdrawn", status=ApplicationStatus.WITHDRAWN),
    )
    use_case = ListTrackedApplications(repository=repository)

    outputs = await use_case.execute(
        ListTrackedApplicationsInput(user_id=_USER, open_only=True)
    )

    assert {output.id for output in outputs} == {"applied", "interviewing", "offer"}
    assert all(output.is_open for output in outputs)


async def test_open_only_never_asks_for_draft() -> None:
    """`draft` is non-terminal but cannot describe a sent application, so the
    open filter must not include it — a tracked row can never match it, and
    asking would misstate what the view means."""
    repository = _repository(_application())
    captured: list[object] = []

    original = repository.list_by_user_id

    async def recording(user_id, *, statuses=None, limit=100):  # type: ignore[no-untyped-def]
        captured.append(statuses)
        return await original(user_id, statuses=statuses, limit=limit)

    repository.list_by_user_id = recording  # type: ignore[method-assign]
    use_case = ListTrackedApplications(repository=repository)

    await use_case.execute(ListTrackedApplicationsInput(user_id=_USER, open_only=True))

    (statuses,) = captured
    assert ApplicationStatus.DRAFT not in statuses  # type: ignore[operator]


async def test_the_status_filter_is_pushed_into_the_repository_call() -> None:
    """Filtering in the query is the point — a use case that fetched everything
    and filtered in Python would pass an assertion on the returned list."""
    repository = _repository(_application())
    captured: list[object] = []

    original = repository.list_by_user_id

    async def recording(user_id, *, statuses=None, limit=100):  # type: ignore[no-untyped-def]
        captured.append(statuses)
        return await original(user_id, statuses=statuses, limit=limit)

    repository.list_by_user_id = recording  # type: ignore[method-assign]
    use_case = ListTrackedApplications(repository=repository)

    await use_case.execute(
        ListTrackedApplicationsInput(user_id=_USER, statuses=("offer",))
    )

    assert captured == [(ApplicationStatus.OFFER,)]


async def test_a_repeated_status_in_the_filter_is_de_duplicated() -> None:
    repository = _repository(_application())
    captured: list[object] = []

    original = repository.list_by_user_id

    async def recording(user_id, *, statuses=None, limit=100):  # type: ignore[no-untyped-def]
        captured.append(statuses)
        return await original(user_id, statuses=statuses, limit=limit)

    repository.list_by_user_id = recording  # type: ignore[method-assign]
    use_case = ListTrackedApplications(repository=repository)

    await use_case.execute(
        ListTrackedApplicationsInput(
            user_id=_USER, statuses=("applied", "applied", "offer")
        )
    )

    assert captured == [(ApplicationStatus.APPLIED, ApplicationStatus.OFFER)]


async def test_an_empty_status_filter_matches_nothing() -> None:
    """Distinct from no filter at all: a caller that narrowed its own list to
    nothing asked a different question than one that did not narrow."""
    repository = _repository(_application())
    use_case = ListTrackedApplications(repository=repository)

    outputs = await use_case.execute(
        ListTrackedApplicationsInput(user_id=_USER, statuses=())
    )

    assert outputs == []


async def test_an_unknown_status_in_the_filter_is_refused() -> None:
    use_case = ListTrackedApplications(repository=_repository(_application()))

    with pytest.raises(InvalidValueError, match="is not an application status"):
        await use_case.execute(
            ListTrackedApplicationsInput(user_id=_USER, statuses=("ghosted",))
        )


async def test_asking_for_open_and_specific_statuses_at_once_is_refused() -> None:
    use_case = ListTrackedApplications(repository=_repository(_application()))

    with pytest.raises(InvalidValueError, match="not both"):
        await use_case.execute(
            ListTrackedApplicationsInput(
                user_id=_USER, open_only=True, statuses=("rejected",)
            )
        )


async def test_the_feed_carries_each_applications_history() -> None:
    application = _application()
    application.change_status(ApplicationStatus.INTERVIEWING)
    use_case = ListTrackedApplications(repository=_repository(application))

    (output,) = await use_case.execute(ListTrackedApplicationsInput(user_id=_USER))

    assert [entry.status for entry in output.status_history] == [
        "applied",
        "interviewing",
    ]


async def test_applications_to_one_posting_are_listed_together() -> None:
    repository = _repository(
        _application("first", job_posting_id="job-1", applied_at=_APPLIED_AT),
        _application(
            "again",
            job_posting_id="job-1",
            applied_at=_APPLIED_AT + timedelta(days=180),
        ),
        _application("elsewhere", job_posting_id="job-2"),
    )
    use_case = ListApplicationsForJob(repository=repository)

    outputs = await use_case.execute(
        ListApplicationsForJobInput(user_id=_USER, job_posting_id="job-1")
    )

    assert [output.id for output in outputs] == ["again", "first"]
