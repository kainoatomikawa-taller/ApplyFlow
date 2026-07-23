"""UploadResume use case — validate, extract text from, and store a resume.

One class, one `execute(dto)` method. Dependencies (repository, storage,
text extractor, id generator) are injected via the constructor as
abstractions — this use case never knows it's writing to local disk or
parsing with `pypdf`.
"""

from __future__ import annotations

from src.application.dtos.resume_dtos import ResumeOutput, UploadResumeInput
from src.application.mappers.resume_mapper import ResumeMapper
from src.application.ports.file_storage_port import FileStoragePort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.text_extractor_port import TextExtractorPort
from src.domain.entities.resume import Resume
from src.domain.repositories.resume_repository import ResumeRepository


class UploadResume:
    def __init__(
        self,
        repository: ResumeRepository,
        storage: FileStoragePort,
        text_extractor: TextExtractorPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._text_extractor = text_extractor
        self._id_generator = id_generator

    async def execute(self, dto: UploadResumeInput) -> ResumeOutput:
        # Validate format/size up front — before spending any time parsing
        # or writing bytes to disk — using the same rule `Resume` enforces
        # on construction.
        Resume.ensure_supported_format(dto.content_type)
        Resume.ensure_within_size_limit(len(dto.content))

        extracted_text = self._text_extractor.extract_text(
            dto.content, dto.content_type
        )

        # An opaque, server-generated key — never derived from the
        # candidate's filename or email — so the storage layer and any
        # logs it emits carry no PII.
        storage_key = self._id_generator.new_id()
        resume = Resume(
            id=self._id_generator.new_id(),
            user_id=dto.user_id,
            original_filename=dto.original_filename,
            content_type=dto.content_type,
            size_bytes=len(dto.content),
            storage_key=storage_key,
            extracted_text=extracted_text,
        )

        await self._storage.save(storage_key, dto.content)
        try:
            await self._repository.add(resume)
        except Exception:
            # Don't orphan a stored file if its metadata row never lands.
            await self._storage.delete(storage_key)
            raise

        return ResumeMapper.to_output(resume)
