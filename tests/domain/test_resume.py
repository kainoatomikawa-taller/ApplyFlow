import pytest

from src.domain.entities.resume import Resume
from src.domain.exceptions import (
    FileTooLargeError,
    InvalidValueError,
    UnsupportedFileFormatError,
)


def _resume(
    *,
    id: str = "resume-1",
    user_id: str = "user-1",
    original_filename: str = "my_resume.pdf",
    content_type: str = "application/pdf",
    size_bytes: int = 1024,
    storage_key: str = "storage-key-1",
    extracted_text: str = "Jane Doe, Software Engineer.",
) -> Resume:
    return Resume(
        id=id,
        user_id=user_id,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_key=storage_key,
        extracted_text=extracted_text,
    )


def test_valid_resume_constructs():
    resume = _resume()
    assert resume.content_type == "application/pdf"
    assert resume.size_bytes == 1024


def test_docx_and_plain_text_are_supported_formats():
    _resume(
        content_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
    )
    _resume(content_type="text/plain")


def test_unsupported_content_type_rejected():
    with pytest.raises(UnsupportedFileFormatError):
        _resume(content_type="image/png")


def test_oversized_file_rejected():
    with pytest.raises(FileTooLargeError):
        _resume(size_bytes=Resume.MAX_SIZE_BYTES + 1)


def test_zero_byte_file_rejected():
    with pytest.raises(FileTooLargeError):
        _resume(size_bytes=0)


def test_empty_id_rejected():
    with pytest.raises(InvalidValueError):
        _resume(id="")


def test_empty_filename_rejected():
    with pytest.raises(InvalidValueError):
        _resume(original_filename="   ")


def test_empty_storage_key_rejected():
    with pytest.raises(InvalidValueError):
        _resume(storage_key="")


def test_ensure_supported_format_helper_raises_directly():
    with pytest.raises(UnsupportedFileFormatError):
        Resume.ensure_supported_format("application/zip")


def test_ensure_within_size_limit_helper_raises_directly():
    with pytest.raises(FileTooLargeError):
        Resume.ensure_within_size_limit(Resume.MAX_SIZE_BYTES + 1)
