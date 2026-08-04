"""Mapper between the EEO self-identification record and its output DTO.

Its own module, separate from `profile_mapper.py`, and that separation is the
point rather than tidiness. A static guard
(`test_the_eeo_record_is_unreachable_from_every_form_filling_module`) allows only
a named list of modules to read this record; keeping the mapping here means the
main profile mapper — which every profile view goes through — stays off that list
and cannot accidentally start serving demographic data.

Read the guard's allowlist before adding a caller. The rule it enforces is that
nothing on the way to an application form may touch this record; a profile editor
is not on that path, which is why these modules are permitted and a prompt
builder or field resolver never will be.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import EeoSelfIdentificationOutput
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification


class EeoMapper:
    """Translates the EEO record into its output DTO."""

    @staticmethod
    def to_output(
        record: EeoSelfIdentification | None, *, consent_granted: bool
    ) -> EeoSelfIdentificationOutput:
        """Render the record, or the all-unanswered state when there is none.

        A record is returned either way rather than None, because "you have not
        answered these" is a state the editor has to draw, and making the caller
        branch on absence would put that decision in every consumer.
        """
        if record is None:
            return EeoSelfIdentificationOutput(
                gender_identity=None,
                race_ethnicity=None,
                veteran_status=None,
                disability_status=None,
                source=None,
                consent_granted=consent_granted,
            )
        return EeoSelfIdentificationOutput(
            gender_identity=_value(record.gender_identity),
            race_ethnicity=_value(record.race_ethnicity),
            veteran_status=_value(record.veteran_status),
            disability_status=_value(record.disability_status),
            source=record.source.value,
            consent_granted=consent_granted,
        )


def _value(category: object) -> str | None:
    """The enum's stored value, or None for a category left unanswered.

    None survives as None: an unanswered category is not the same as
    `DECLINE_TO_SELF_IDENTIFY`, which is one of the answers.
    """
    return None if category is None else str(category)
