"""ResumeParserPort — an outbound port for LLM-driven resume parsing.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed on
the cheap tier via `LlmTaskType.PARSING`). The use case never knows which
model or provider answers the call.

Every field below is optional at this boundary: a resume is often
incomplete or messy, and the parser must never invent a value it didn't
actually read from the text. Callers (see `ParseResume`) decide what to do
when a required domain field is missing — this port only reports what was
found.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from src.domain.value_objects.proficiency_level import ProficiencyLevel


@dataclass(frozen=True)
class ParsedWorkHistoryEntry:
    """One employment period as read from the resume text."""

    company_name: str | None = None
    job_title: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ParsedEducationEntry:
    """One program of study as read from the resume text."""

    institution_name: str | None = None
    degree: str | None = None
    #: Subjects read as majors and as minors. Separate because the domain keeps
    #: them separate, and because promoting a minor to a major would overstate a
    #: credential (see `EducationEntry`).
    majors: list[str] = field(default_factory=list)
    minors: list[str] = field(default_factory=list)
    #: Retained as a fallback for a model that answers with the older single
    #: field: `ParseResume` reads it as one major when `majors` is empty. Keeping
    #: it costs one branch and avoids losing the subject entirely on a response
    #: that drifts back to the previous shape.
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


@dataclass(frozen=True)
class ParsedSkill:
    """One skill as read from the resume text."""

    name: str | None = None
    proficiency: ProficiencyLevel | None = None
    years_of_experience: int | None = None


@dataclass(frozen=True)
class ParsedResumeData:
    """Structured facts extracted from a resume's text.

    Matches the shape of `UserProfile`'s core data model (contact info,
    work history, education, skills) minus anything the parser couldn't
    determine — those fields are `None`/empty rather than guessed.
    """

    full_name: str | None = None
    middle_name: str | None = None
    #: A name given in addition to the legal one — "Michael (Mike) Chen" — never
    #: a shortening the parser thought up on its own.
    preferred_name: str | None = None
    email: str | None = None
    phone: str | None = None
    headline: str | None = None
    location: str | None = None
    #: Postal address, as far as the resume states it. Most give a city and
    #: little else, which is why every part is independently optional.
    street_address: str | None = None
    city: str | None = None
    state_or_region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    #: Profile URLs a resume header usually lists. Kept apart from each other
    #: rather than as one "links" blob so an unrecognizable one can be dropped
    #: without taking the others with it.
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    work_history: list[ParsedWorkHistoryEntry] = field(default_factory=list)
    education: list[ParsedEducationEntry] = field(default_factory=list)
    skills: list[ParsedSkill] = field(default_factory=list)


class ResumeParserPort(ABC):
    """Abstraction over an LLM-driven resume-to-structured-data parser."""

    @abstractmethod
    async def parse(self, resume_text: str) -> ParsedResumeData:
        """Extract structured facts from raw resume text.

        Raises `src.application.exceptions.ExternalServiceError` if the
        call fails or the model's response cannot be interpreted.
        """
