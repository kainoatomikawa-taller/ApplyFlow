"""RequirementCategory value object — which attribute of a job posting's
description a classified requirement came from."""

from __future__ import annotations

from enum import StrEnum


class RequirementCategory(StrEnum):
    DEGREE = "degree"
    CLEARANCE = "clearance"
    LOCATION = "location"
    WORK_AUTHORIZATION = "work_authorization"
    EXPERIENCE = "experience"
    SKILL = "skill"
    PREFERENCE = "preference"
