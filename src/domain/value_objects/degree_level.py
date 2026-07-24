"""DegreeLevel value object — the minimum education level a job posting
states it requires or prefers."""

from __future__ import annotations

from enum import StrEnum


class DegreeLevel(StrEnum):
    HIGH_SCHOOL = "high_school"
    ASSOCIATE = "associate"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DOCTORATE = "doctorate"
