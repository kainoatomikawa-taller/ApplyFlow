"""DTOs — input/output contracts for the requirement-classification use
case. DTOs are plain data with no behavior; output DTOs flatten domain
enums to their string values so use cases never leak domain types across
the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClassifyJobRequirementsInput:
    job_posting_id: str


@dataclass(frozen=True)
class ClassifiedRequirementOutput:
    category: str
    description: str


@dataclass(frozen=True)
class RequirementClassificationOutput:
    job_posting_id: str
    hard: list[ClassifiedRequirementOutput] = field(default_factory=list)
    soft: list[ClassifiedRequirementOutput] = field(default_factory=list)
