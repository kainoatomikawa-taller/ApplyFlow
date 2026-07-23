"""Resume use case tests using in-memory fakes for the ports/repository.

Demonstrates the application layer depends only on abstractions: no disk
or parsing library is required to test it.
"""

import pytest

from src.application.dtos.resume_dtos import UploadResumeInput
from src.application.exceptions import TextExtractionError
from src.application.ports.file_storage_port import FileStoragePort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.text_extractor_port import TextExtractorPort
from src.application.use_cases.get_resume import GetResume
from src.application.use_cases.list_resumes import ListResumes
from src.application.use_cases.upload_resume import UploadResume
from src.domain.entities.resume import Resume
from src.domain.exceptions import (
    FileTooLargeError,
    ResumeNotFoundError,
    UnsupportedFileFormatError,
)
from src.domain.repositories.resume_repository import ResumeRepository


class InMemoryResumeRepo(ResumeRepository):
    def __init__(self) -> None:
        self.store: dict[str, Resume] = {}
        self.raise_on_add = False

    async def add(self, resume: Resume) -> None:
        if self.raise_on_add:
            raise RuntimeError("simulated persistence failure")
        self.store[resume.id] = resume

    async def get_by_id(self, resume_id: str) -> Resume | None:
        return self.store.get(resume_id)

    async def list_by_user_id(self, user_id: str) -> list[Resume]:
        return [r for r in self.store.values() if r.user_id == user_id]

    async def delete(self, resume_id: str) -> None:
        self.store.pop(resume_id, None)


class InMemoryFileStorage(FileStoragePort):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    async def save(self, storage_key: str, content: bytes) -> None:
        self.saved[storage_key] = content

    async def delete(self, storage_key: str) -> None:
        self.saved.pop(storage_key, None)


class FakeTextExtractor(TextExtractorPort):
    def extract_text(self, content: bytes, content_type: str) -> str:
        return content.decode("utf-8")


class FailingTextExtractor(TextExtractorPort):
    def extract_text(self, content: bytes, content_type: str) -> str:
        raise TextExtractionError("could not parse this file")


class SequentialIdGenerator(IdGeneratorPort):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next}"


def _upload_input(**overrides) -> UploadResumeInput:
    defaults: dict = dict(
        user_id="user-1",
        original_filename="resume.txt",
        content_type="text/plain",
        content=b"Jane Doe, Software Engineer.",
    )
    defaults.update(overrides)
    return UploadResumeInput(**defaults)


@pytest.mark.asyncio
async def test_upload_resume_stores_file_and_metadata():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()

    output = await UploadResume(
        repository=repo,
        storage=storage,
        text_extractor=FakeTextExtractor(),
        id_generator=SequentialIdGenerator(),
    ).execute(_upload_input())

    assert output.id == "id-2"
    assert output.original_filename == "resume.txt"
    assert output.extracted_text == "Jane Doe, Software Engineer."
    assert output.size_bytes == len(b"Jane Doe, Software Engineer.")

    # Stored under the first generated id (the storage key), distinct from
    # the resume's own id and never derived from the original filename.
    assert storage.saved == {"id-1": b"Jane Doe, Software Engineer."}
    assert repo.store["id-2"].storage_key == "id-1"


@pytest.mark.asyncio
async def test_upload_resume_rejects_unsupported_format_before_extracting():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()

    with pytest.raises(UnsupportedFileFormatError):
        await UploadResume(
            repository=repo,
            storage=storage,
            text_extractor=FailingTextExtractor(),
            id_generator=SequentialIdGenerator(),
        ).execute(_upload_input(content_type="image/png"))

    assert storage.saved == {}
    assert repo.store == {}


@pytest.mark.asyncio
async def test_upload_resume_rejects_oversized_file_before_extracting():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()

    with pytest.raises(FileTooLargeError):
        await UploadResume(
            repository=repo,
            storage=storage,
            text_extractor=FailingTextExtractor(),
            id_generator=SequentialIdGenerator(),
        ).execute(
            _upload_input(content=b"x" * (Resume.MAX_SIZE_BYTES + 1))
        )

    assert storage.saved == {}
    assert repo.store == {}


@pytest.mark.asyncio
async def test_upload_resume_surfaces_text_extraction_errors():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()

    with pytest.raises(TextExtractionError):
        await UploadResume(
            repository=repo,
            storage=storage,
            text_extractor=FailingTextExtractor(),
            id_generator=SequentialIdGenerator(),
        ).execute(_upload_input())

    # Nothing was written — extraction happens before storage/persistence.
    assert storage.saved == {}
    assert repo.store == {}


@pytest.mark.asyncio
async def test_upload_resume_cleans_up_stored_file_if_persistence_fails():
    repo = InMemoryResumeRepo()
    repo.raise_on_add = True
    storage = InMemoryFileStorage()

    with pytest.raises(RuntimeError):
        await UploadResume(
            repository=repo,
            storage=storage,
            text_extractor=FakeTextExtractor(),
            id_generator=SequentialIdGenerator(),
        ).execute(_upload_input())

    # The file was written, then cleaned up once the metadata write failed.
    assert storage.saved == {}


@pytest.mark.asyncio
async def test_get_resume_returns_owners_resume():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()
    uploaded = await UploadResume(
        repository=repo,
        storage=storage,
        text_extractor=FakeTextExtractor(),
        id_generator=SequentialIdGenerator(),
    ).execute(_upload_input(user_id="user-1"))

    output = await GetResume(repo).execute(uploaded.id, "user-1")
    assert output.id == uploaded.id


@pytest.mark.asyncio
async def test_get_resume_hides_another_users_resume_as_not_found():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()
    uploaded = await UploadResume(
        repository=repo,
        storage=storage,
        text_extractor=FakeTextExtractor(),
        id_generator=SequentialIdGenerator(),
    ).execute(_upload_input(user_id="user-1"))

    with pytest.raises(ResumeNotFoundError):
        await GetResume(repo).execute(uploaded.id, "someone-else")


@pytest.mark.asyncio
async def test_get_resume_raises_for_unknown_id():
    repo = InMemoryResumeRepo()
    with pytest.raises(ResumeNotFoundError):
        await GetResume(repo).execute("does-not-exist", "user-1")


@pytest.mark.asyncio
async def test_list_resumes_scopes_to_requesting_user():
    repo = InMemoryResumeRepo()
    storage = InMemoryFileStorage()
    use_case = UploadResume(
        repository=repo,
        storage=storage,
        text_extractor=FakeTextExtractor(),
        id_generator=SequentialIdGenerator(),
    )
    await use_case.execute(_upload_input(user_id="user-1"))
    await use_case.execute(_upload_input(user_id="user-2"))

    outputs = await ListResumes(repo).execute("user-1")
    assert len(outputs) == 1
