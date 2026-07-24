"""ParseResume use case — extract structured facts from a resume via the
LLM layer and persist them onto the candidate's profile.

Every fact this use case adds is tagged `ProvenanceSource.PARSED_RESUME` —
see `src/domain/value_objects/provenance_source.py` for the downstream
contract that depends on that tag being accurate. Nothing here is ever
invented: a parsed field that's missing or unusable is skipped rather than
defaulted, so a messy or incomplete resume degrades gracefully instead of
polluting the profile with fabricated data.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.resume_parser_port import ParsedResumeData, ResumeParserPort
from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import ProfileMissingContactInfoError, ResumeNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.repositories.resume_repository import ResumeRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.provenance_source import ProvenanceSource


def _clean(value: str | None) -> str | None:
    """Normalize a possibly-empty/whitespace-only parsed string to None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ParseResume:
    def __init__(
        self,
        resume_repository: ResumeRepository,
        profile_repository: ProfileRepository,
        resume_parser: ResumeParserPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._resume_repository = resume_repository
        self._profile_repository = profile_repository
        self._resume_parser = resume_parser
        self._id_generator = id_generator

    async def execute(self, resume_id: str, user_id: str) -> ProfileOutput:
        resume = await self._resume_repository.get_by_id(resume_id)
        if resume is None or resume.user_id != user_id:
            raise ResumeNotFoundError(resume_id)

        parsed = await self._resume_parser.parse(resume.extracted_text)

        profile = await self._profile_repository.get_by_user_id(user_id)
        is_new_profile = profile is None
        if profile is None:
            profile = self._new_profile(user_id, parsed)

        self._merge_work_history(profile, parsed)
        self._merge_education(profile, parsed)
        self._merge_skills(profile, parsed)

        if is_new_profile:
            await self._profile_repository.add(profile)
        else:
            await self._profile_repository.update(profile)

        return ProfileMapper.to_output(profile)

    def _new_profile(self, user_id: str, parsed: ParsedResumeData) -> UserProfile:
        full_name = _clean(parsed.full_name)
        email = _clean(parsed.email)
        if full_name is None or email is None:
            raise ProfileMissingContactInfoError()
        return UserProfile(
            id=self._id_generator.new_id(),
            user_id=user_id,
            full_name=full_name,
            email=EmailAddress(email),
            contact_source=ProvenanceSource.PARSED_RESUME,
            phone=_clean(parsed.phone),
            headline=_clean(parsed.headline),
            location=_clean(parsed.location),
        )

    def _merge_work_history(
        self, profile: UserProfile, parsed: ParsedResumeData
    ) -> None:
        for entry in parsed.work_history:
            company_name = _clean(entry.company_name)
            job_title = _clean(entry.job_title)
            if company_name is None or job_title is None or entry.start_date is None:
                continue
            profile.add_work_history(
                WorkHistoryEntry(
                    id=self._id_generator.new_id(),
                    company_name=company_name,
                    job_title=job_title,
                    start_date=entry.start_date,
                    end_date=entry.end_date,
                    location=_clean(entry.location),
                    description=_clean(entry.description),
                    source=ProvenanceSource.PARSED_RESUME,
                )
            )

    def _merge_education(
        self, profile: UserProfile, parsed: ParsedResumeData
    ) -> None:
        for entry in parsed.education:
            institution_name = _clean(entry.institution_name)
            degree = _clean(entry.degree)
            if institution_name is None or degree is None:
                continue
            profile.add_education(
                EducationEntry(
                    id=self._id_generator.new_id(),
                    institution_name=institution_name,
                    degree=degree,
                    field_of_study=_clean(entry.field_of_study),
                    start_date=entry.start_date,
                    end_date=entry.end_date,
                    description=_clean(entry.description),
                    source=ProvenanceSource.PARSED_RESUME,
                )
            )

    def _merge_skills(self, profile: UserProfile, parsed: ParsedResumeData) -> None:
        # `Skill.name` is unique per profile (case-insensitive) — a messy
        # resume can easily repeat a skill (once in a summary, again in a
        # skills list), and re-parsing must not collide with facts already
        # on the profile, so both are deduped here rather than left to
        # blow up `UserProfile.add_skill`.
        existing_names = {s.name.strip().lower() for s in profile.skills}
        seen_in_batch: set[str] = set()
        for skill in parsed.skills:
            name = _clean(skill.name)
            if name is None:
                continue
            key = name.lower()
            if key in existing_names or key in seen_in_batch:
                continue
            seen_in_batch.add(key)
            years = skill.years_of_experience
            if years is not None and years < 0:
                years = None
            profile.add_skill(
                Skill(
                    id=self._id_generator.new_id(),
                    name=name,
                    proficiency=skill.proficiency,
                    years_of_experience=years,
                    source=ProvenanceSource.PARSED_RESUME,
                )
            )
