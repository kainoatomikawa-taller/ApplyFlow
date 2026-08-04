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

from datetime import date

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
from src.domain.services.text_normalization import normalize_text
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
        # Deduped against what the profile already holds, and within the batch —
        # the same two reasons the skills merge below has always done it.
        #
        # This matters more now that the profile is editable. Parsing used to be
        # the only way work history got onto a profile, so a duplicate could only
        # come from parsing the same résumé twice — still a real defect, and one
        # the candidate could not clean up, because nothing could delete an entry.
        # Now that typing history by hand and uploading a résumé are both
        # supported, and explicitly meant to be combinable, a candidate who fills
        # in the jobs a résumé missed and then re-uploads it would otherwise get a
        # second copy of everything.
        seen = {_work_history_key(e) for e in profile.work_history}
        for entry in parsed.work_history:
            company_name = _clean(entry.company_name)
            job_title = _clean(entry.job_title)
            if company_name is None or job_title is None or entry.start_date is None:
                continue
            candidate = WorkHistoryEntry(
                id=self._id_generator.new_id(),
                company_name=company_name,
                job_title=job_title,
                start_date=entry.start_date,
                end_date=entry.end_date,
                location=_clean(entry.location),
                description=_clean(entry.description),
                source=ProvenanceSource.PARSED_RESUME,
            )
            key = _work_history_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            profile.add_work_history(candidate)

    def _merge_education(self, profile: UserProfile, parsed: ParsedResumeData) -> None:
        seen = {_education_key(e) for e in profile.education}
        for entry in parsed.education:
            institution_name = _clean(entry.institution_name)
            degree = _clean(entry.degree)
            if institution_name is None or degree is None:
                continue
            candidate = EducationEntry(
                id=self._id_generator.new_id(),
                institution_name=institution_name,
                degree=degree,
                field_of_study=_clean(entry.field_of_study),
                start_date=entry.start_date,
                end_date=entry.end_date,
                description=_clean(entry.description),
                source=ProvenanceSource.PARSED_RESUME,
            )
            key = _education_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            profile.add_education(candidate)

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


def _work_history_key(entry: WorkHistoryEntry) -> tuple[str, str, date]:
    """What makes two work-history entries "the same job".

    Company, title, and start date — normalized for case and spacing so "ACME
    Corp" and "Acme  Corp" collapse, using the same `normalize_text` the job-dedup
    logic uses elsewhere.

    Deliberately an exact normalized match rather than the fuzzier
    `titles_match`, which treats one title as matching another it contains.
    "Engineer" and "Senior Engineer" at the same company on the same start date
    would collapse under that rule, and they are plausibly two real entries —
    a promotion the candidate listed separately. Over-merging silently deletes
    history the candidate entered; under-merging leaves a duplicate they can now
    delete themselves.

    The start date is in the key because it is the field that distinguishes two
    stints at the same employer in the same role, which is common enough
    (contract, then permanent) to matter.
    """
    return (
        normalize_text(entry.company_name),
        normalize_text(entry.job_title),
        entry.start_date,
    )


def _education_key(entry: EducationEntry) -> tuple[str, str, date | None]:
    """What makes two education entries "the same qualification".

    Institution, degree, and start date. The start date is optional here — plenty
    of résumés give only an end year — so `None` participates in the key rather
    than being treated as a wildcard: two entries for the same degree at the same
    institution, one dated and one not, stay separate, because merging them would
    have to choose which one's dates to keep.
    """
    return (
        normalize_text(entry.institution_name),
        normalize_text(entry.degree),
        entry.start_date,
    )
