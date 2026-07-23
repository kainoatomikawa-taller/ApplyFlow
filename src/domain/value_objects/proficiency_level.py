"""ProficiencyLevel value object — self-reported skill proficiency."""

from __future__ import annotations

from enum import StrEnum


class ProficiencyLevel(StrEnum):
    """How proficient a candidate is at a given skill."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
