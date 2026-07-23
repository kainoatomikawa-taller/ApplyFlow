"""LocalFileStorage — filesystem implementation of `FileStoragePort`.

Stores each file under `base_dir / storage_key`, with no other path
component. `storage_key` is always a server-generated id (see
`UploadResume`), never derived from user input, so there is no path to
sanitize against traversal — but `_resolve` still asserts the resolved
path stays inside `base_dir` as a defense-in-depth check.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.application.ports.file_storage_port import FileStoragePort


class LocalFileStorage(FileStoragePort):
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, storage_key: str, content: bytes) -> None:
        path = self._resolve(storage_key)
        await asyncio.to_thread(path.write_bytes, content)

    async def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        path = (self._base_dir / storage_key).resolve()
        if self._base_dir not in path.parents:
            raise ValueError(f"Invalid storage key: '{storage_key}'.")
        return path
