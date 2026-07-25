"""Tests for reading and archiving stored sent-document snapshots.

The reads exist so the tracker (Epic 06) and interview prep get the document
that was actually produced instead of a fresh one, so what is under test is:
does a caller get exactly that text, only their own, and does "latest" mean
what the newest generation produced.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.application_document_dtos import (
    GetApplicationDocumentInput,
    GetLatestApplicationDocumentInput,
    ListApplicationDocumentsInput,
)
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.use_cases.get_application_document import GetApplicationDocument
from src.application.use_cases.get_latest_application_document import (
    GetLatestApplicationDocument,
)
from src.application.use_cases.list_application_documents import (
    ListApplicationDocuments,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.exceptions import (
    ApplicationDocumentNotFoundError,
    InvalidValueError,
    NoStoredApplicationDocumentError,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    SequentialIdGenerator,
)

_RESUME_TEXT = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"
_LETTER_TEXT = "Dear Hiring Manager,\n\nI led a team of 5 engineers.\n\nSincerely,"
_EPOCH = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _document(
    *,
    document_id: str = "doc-1",
    user_id: str = "user-1",
    job_posting_id: str = "job-1",
    kind: GeneratedDocumentKind = GeneratedDocumentKind.TAILORED_RESUME,
    content: str = _RESUME_TEXT,
    version: int = 1,
    minutes_old: int = 0,
) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
        created_at=_EPOCH - timedelta(minutes=minutes_old),
    )


# ---- GetApplicationDocument -------------------------------------------------


@pytest.mark.asyncio
async def test_a_stored_document_comes_back_with_its_exact_text():
    repository = InMemoryApplicationDocumentRepository([_document()])
    use_case = GetApplicationDocument(repository=repository)

    output = await use_case.execute(
        GetApplicationDocumentInput(user_id="user-1", document_id="doc-1")
    )

    assert output.content == _RESUME_TEXT
    assert output.document_kind == "tailored_resume"
    assert output.version == 1
    assert output.backing_sources == ["parsed_resume"]


@pytest.mark.asyncio
async def test_the_digest_travels_with_the_document_so_it_can_be_verified():
    document = _document()
    use_case = GetApplicationDocument(
        repository=InMemoryApplicationDocumentRepository([document])
    )

    output = await use_case.execute(
        GetApplicationDocumentInput(user_id="user-1", document_id="doc-1")
    )

    assert output.content_sha256 == document.content_sha256


@pytest.mark.asyncio
async def test_another_candidates_document_is_reported_as_not_found():
    """Not "forbidden": the API must not confirm someone else's ids exist."""
    repository = InMemoryApplicationDocumentRepository([_document(user_id="user-2")])
    use_case = GetApplicationDocument(repository=repository)

    with pytest.raises(ApplicationDocumentNotFoundError):
        await use_case.execute(
            GetApplicationDocumentInput(user_id="user-1", document_id="doc-1")
        )


@pytest.mark.asyncio
async def test_an_unknown_id_raises_rather_than_returning_nothing():
    use_case = GetApplicationDocument(
        repository=InMemoryApplicationDocumentRepository()
    )

    with pytest.raises(ApplicationDocumentNotFoundError):
        await use_case.execute(
            GetApplicationDocumentInput(user_id="user-1", document_id="missing")
        )


# ---- GetLatestApplicationDocument -------------------------------------------


@pytest.mark.asyncio
async def test_the_latest_version_is_what_the_application_went_out_with():
    repository = InMemoryApplicationDocumentRepository(
        [
            _document(document_id="doc-1", content="First draft", version=1),
            _document(document_id="doc-2", content=_RESUME_TEXT, version=2),
        ]
    )
    use_case = GetLatestApplicationDocument(repository=repository)

    output = await use_case.execute(
        GetLatestApplicationDocumentInput(
            user_id="user-1",
            job_posting_id="job-1",
            document_kind="tailored_resume",
        )
    )

    assert output.id == "doc-2"
    assert output.content == _RESUME_TEXT


@pytest.mark.asyncio
async def test_each_kind_is_looked_up_on_its_own():
    repository = InMemoryApplicationDocumentRepository(
        [
            _document(document_id="doc-1"),
            _document(
                document_id="doc-2",
                kind=GeneratedDocumentKind.COVER_LETTER,
                content=_LETTER_TEXT,
            ),
        ]
    )
    use_case = GetLatestApplicationDocument(repository=repository)

    output = await use_case.execute(
        GetLatestApplicationDocumentInput(
            user_id="user-1", job_posting_id="job-1", document_kind="cover_letter"
        )
    )

    assert output.content == _LETTER_TEXT


@pytest.mark.asyncio
async def test_a_job_nothing_was_produced_for_says_so_instead_of_returning_empty():
    use_case = GetLatestApplicationDocument(
        repository=InMemoryApplicationDocumentRepository()
    )

    with pytest.raises(NoStoredApplicationDocumentError) as exc_info:
        await use_case.execute(
            GetLatestApplicationDocumentInput(
                user_id="user-1",
                job_posting_id="job-1",
                document_kind="cover_letter",
            )
        )

    assert exc_info.value.job_posting_id == "job-1"
    assert exc_info.value.document_kind == "cover_letter"


@pytest.mark.asyncio
async def test_another_candidates_job_documents_are_not_reachable():
    repository = InMemoryApplicationDocumentRepository([_document(user_id="user-2")])
    use_case = GetLatestApplicationDocument(repository=repository)

    with pytest.raises(NoStoredApplicationDocumentError):
        await use_case.execute(
            GetLatestApplicationDocumentInput(
                user_id="user-1",
                job_posting_id="job-1",
                document_kind="tailored_resume",
            )
        )


@pytest.mark.asyncio
async def test_an_unrecognized_document_kind_is_rejected():
    use_case = GetLatestApplicationDocument(
        repository=InMemoryApplicationDocumentRepository()
    )

    with pytest.raises(InvalidValueError):
        await use_case.execute(
            GetLatestApplicationDocumentInput(
                user_id="user-1", job_posting_id="job-1", document_kind="portfolio"
            )
        )


# ---- ListApplicationDocuments -----------------------------------------------


@pytest.mark.asyncio
async def test_the_tracker_feed_lists_a_candidates_documents_newest_first():
    repository = InMemoryApplicationDocumentRepository(
        [
            _document(document_id="older", minutes_old=60),
            _document(document_id="newer", job_posting_id="job-2"),
        ]
    )
    use_case = ListApplicationDocuments(repository=repository)

    outputs = await use_case.execute(ListApplicationDocumentsInput(user_id="user-1"))

    assert [o.id for o in outputs] == ["newer", "older"]


@pytest.mark.asyncio
async def test_a_listing_carries_no_document_text():
    """Thirty applications should not mean thirty full resumes in one
    response — the summary is what a list view needs."""
    repository = InMemoryApplicationDocumentRepository([_document()])
    use_case = ListApplicationDocuments(repository=repository)

    outputs = await use_case.execute(ListApplicationDocumentsInput(user_id="user-1"))

    assert not hasattr(outputs[0], "content")
    assert outputs[0].content_sha256


@pytest.mark.asyncio
async def test_one_job_can_be_listed_on_its_own_with_every_version():
    repository = InMemoryApplicationDocumentRepository(
        [
            _document(document_id="doc-1", version=1, minutes_old=60),
            _document(document_id="doc-2", version=2),
            _document(document_id="other-job", job_posting_id="job-2"),
        ]
    )
    use_case = ListApplicationDocuments(repository=repository)

    outputs = await use_case.execute(
        ListApplicationDocumentsInput(user_id="user-1", job_posting_id="job-1")
    )

    assert [o.id for o in outputs] == ["doc-2", "doc-1"]


@pytest.mark.asyncio
async def test_only_the_requesting_candidates_documents_are_listed():
    repository = InMemoryApplicationDocumentRepository(
        [_document(document_id="mine"), _document(document_id="theirs", user_id="u-2")]
    )
    use_case = ListApplicationDocuments(repository=repository)

    outputs = await use_case.execute(ListApplicationDocumentsInput(user_id="user-1"))

    assert [o.id for o in outputs] == ["mine"]


@pytest.mark.asyncio
async def test_the_listing_honors_its_limit():
    repository = InMemoryApplicationDocumentRepository(
        [_document(document_id=f"doc-{n}", minutes_old=n) for n in range(5)]
    )
    use_case = ListApplicationDocuments(repository=repository)

    outputs = await use_case.execute(
        ListApplicationDocumentsInput(user_id="user-1", limit=2)
    )

    assert [o.id for o in outputs] == ["doc-0", "doc-1"]


# ---- ApplicationDocumentArchive ---------------------------------------------


@pytest.mark.asyncio
async def test_the_archive_stores_content_verbatim():
    repository = InMemoryApplicationDocumentRepository()
    archive = ApplicationDocumentArchive(
        repository=repository, id_generator=SequentialIdGenerator()
    )

    stored = await archive.store(
        user_id="user-1",
        job_posting_id="job-1",
        document_kind=GeneratedDocumentKind.COVER_LETTER,
        content=_LETTER_TEXT,
        backing_sources=(ProvenanceSource.ANSWER,),
    )

    assert stored.content == _LETTER_TEXT
    assert repository.documents == [stored]


@pytest.mark.asyncio
async def test_the_archive_numbers_each_kind_within_its_own_job():
    repository = InMemoryApplicationDocumentRepository()
    archive = ApplicationDocumentArchive(
        repository=repository, id_generator=SequentialIdGenerator()
    )

    async def store(job_posting_id: str, kind: GeneratedDocumentKind) -> int:
        document = await archive.store(
            user_id="user-1",
            job_posting_id=job_posting_id,
            document_kind=kind,
            content=_RESUME_TEXT,
            backing_sources=(ProvenanceSource.PARSED_RESUME,),
        )
        return document.version

    resume = GeneratedDocumentKind.TAILORED_RESUME
    letter = GeneratedDocumentKind.COVER_LETTER
    assert await store("job-1", resume) == 1
    assert await store("job-1", resume) == 2
    assert await store("job-1", letter) == 1
    assert await store("job-2", resume) == 1


@pytest.mark.asyncio
async def test_the_archive_never_logs_the_document_it_stored(caplog):
    """Snapshot content is sensitive; the digest is what identifies it."""
    archive = ApplicationDocumentArchive(
        repository=InMemoryApplicationDocumentRepository(),
        id_generator=SequentialIdGenerator(),
    )

    with caplog.at_level(logging.INFO):
        stored = await archive.store(
            user_id="user-1",
            job_posting_id="job-1",
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content=_LETTER_TEXT,
            backing_sources=(ProvenanceSource.ANSWER,),
        )

    assert "led a team of 5 engineers" not in caplog.text
    assert stored.id in caplog.text
    assert stored.content_sha256 in caplog.text


@pytest.mark.asyncio
async def test_the_archive_cannot_store_content_with_no_provenance():
    """There is no way to ask it to keep an unguarded draft: the guard's
    backing sources are what it is given, and none means nothing attested."""
    archive = ApplicationDocumentArchive(
        repository=InMemoryApplicationDocumentRepository(),
        id_generator=SequentialIdGenerator(),
    )

    with pytest.raises(InvalidValueError):
        await archive.store(
            user_id="user-1",
            job_posting_id="job-1",
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content="I am a seasoned architect.",
            backing_sources=(),
        )
