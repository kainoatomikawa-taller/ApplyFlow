"""Mapper between RequirementClassification and its output DTO."""

from __future__ import annotations

from src.application.dtos.requirement_classification_dtos import (
    ClassifiedRequirementOutput,
    RequirementClassificationOutput,
)
from src.domain.services.requirement_classifier import (
    ClassifiedRequirement,
    RequirementClassification,
)


class RequirementClassificationMapper:
    """Translates the domain classification result into an output DTO."""

    @staticmethod
    def to_output(
        job_posting_id: str, classification: RequirementClassification
    ) -> RequirementClassificationOutput:
        return RequirementClassificationOutput(
            job_posting_id=job_posting_id,
            hard=[
                RequirementClassificationMapper._to_item_output(item)
                for item in classification.hard
            ],
            soft=[
                RequirementClassificationMapper._to_item_output(item)
                for item in classification.soft
            ],
        )

    @staticmethod
    def _to_item_output(item: ClassifiedRequirement) -> ClassifiedRequirementOutput:
        return ClassifiedRequirementOutput(
            category=item.category.value, description=item.description
        )
