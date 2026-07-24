"""RemoteType value object — how a job posting describes its work
location arrangement."""

from __future__ import annotations

from enum import StrEnum


class RemoteType(StrEnum):
    ON_SITE = "on_site"
    HYBRID = "hybrid"
    REMOTE = "remote"
