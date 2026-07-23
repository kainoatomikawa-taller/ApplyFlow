from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.storage.local_file_storage import LocalFileStorage


@pytest.mark.asyncio
async def test_save_writes_file_under_base_dir(tmp_path: Path):
    storage = LocalFileStorage(tmp_path / "resumes")

    await storage.save("abc-123", b"file contents")

    assert (tmp_path / "resumes" / "abc-123").read_bytes() == b"file contents"


@pytest.mark.asyncio
async def test_delete_removes_the_file(tmp_path: Path):
    storage = LocalFileStorage(tmp_path / "resumes")
    await storage.save("abc-123", b"file contents")

    await storage.delete("abc-123")

    assert not (tmp_path / "resumes" / "abc-123").exists()


@pytest.mark.asyncio
async def test_delete_is_a_no_op_for_a_missing_key(tmp_path: Path):
    storage = LocalFileStorage(tmp_path / "resumes")
    await storage.delete("never-existed")  # must not raise


@pytest.mark.asyncio
async def test_path_traversal_storage_key_is_rejected(tmp_path: Path):
    storage = LocalFileStorage(tmp_path / "resumes")
    with pytest.raises(ValueError):
        await storage.save("../escaped", b"malicious")


def test_base_dir_is_created_if_missing(tmp_path: Path):
    base_dir = tmp_path / "nested" / "resumes"
    assert not base_dir.exists()

    LocalFileStorage(base_dir)

    assert base_dir.is_dir()
