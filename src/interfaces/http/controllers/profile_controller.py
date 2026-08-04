"""Profile HTTP controller — the editor the candidate fills in themselves.

Thin: validate input -> call use case -> serialize. No business logic, no DB or
file-system access, no domain entity manipulation.

Why this router exists
----------------------
Until it did, a profile could only be *created* by parsing an uploaded résumé,
and could not be read back or corrected at all. Two consequences followed, and
both are fixed here:

* A candidate with no résumé — or one the parser could not read a name and email
  out of — could not have a profile, and so could not use the product.
* `work_authorizations` and `eeo_self_identifications` had no write path in
  production. The entire sensitive-field apparatus (the truth table in
  `decide_sensitive_field`, the encrypted tables, the greedy-label guards, 118
  acceptance tests) ran on records that were always empty.

Per-section endpoints, not one big PUT
--------------------------------------
Each section saves on its own. That is a privacy decision as much as an API one:
correcting a phone number should not put the candidate's citizenship and
demographic answers back on the wire. It also removes the lost-update problem two
browser tabs would otherwise have, without inventing a version token.

`PUT` fully replaces its own section — an omitted field is cleared, which is how a
candidate deletes one.

Ordering
--------
`PUT /api/profile/contact` is a create-or-update and is the only section that can
bring a profile into existence, because `full_name` and `email` are the aggregate's
only mandatory fields. Every other section answers **404** until it exists, and
says so.

Privacy notes
-------------
* **The subject is always the token's.** No endpoint takes a user id or an email;
  the only path parameters are opaque entry ids. See ADR 0003 and
  `tests/interfaces/http/test_no_pii_in_urls.py`.
* **Nothing about the values is logged** — section names, entry ids, and counts
  only. `tests/infrastructure/test_pii_log_call_sites.py` enforces it.
* The EEO record is served by its own two endpoints rather than folded into the
  profile payload, so the mapper every profile view uses never touches it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.profile_dtos import (
    AddressInput,
    ContactDetailsInput,
    EducationInput,
    EducationStandingInput,
    EeoSelfIdentificationInput,
    EeoSelfIdentificationOutput,
    JobSearchPreferencesInput,
    ProfileLinksInput,
    ProfileOutput,
    QualificationsInput,
    SkillInput,
    TermInput,
    WorkAuthorizationInput,
    WorkAuthorizationOutput,
    WorkHistoryInput,
)
from src.application.exceptions import (
    SensitiveStorageNotAcknowledgedError,
    UnknownProfileEnumValueError,
)
from src.application.use_cases.get_eeo_self_identification import (
    GetEeoSelfIdentification,
)
from src.application.use_cases.get_profile import GetProfile
from src.application.use_cases.get_work_authorization import GetWorkAuthorization
from src.application.use_cases.remove_education_entry import RemoveEducationEntry
from src.application.use_cases.remove_skill import RemoveSkill
from src.application.use_cases.remove_work_history_entry import (
    RemoveWorkHistoryEntry,
)
from src.application.use_cases.save_contact_details import SaveContactDetails
from src.application.use_cases.save_education_entry import SaveEducationEntry
from src.application.use_cases.save_eeo_self_identification import (
    SaveEeoSelfIdentification,
)
from src.application.use_cases.save_skill import SaveSkill
from src.application.use_cases.save_work_authorization import SaveWorkAuthorization
from src.application.use_cases.save_work_history_entry import SaveWorkHistoryEntry
from src.application.use_cases.update_education_standing import (
    UpdateEducationStanding,
)
from src.application.use_cases.update_job_search_preferences import (
    UpdateJobSearchPreferences,
)
from src.application.use_cases.update_profile_address import UpdateProfileAddress
from src.application.use_cases.update_profile_links import UpdateProfileLinks
from src.application.use_cases.update_profile_qualifications import (
    UpdateProfileQualifications,
)
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    ProfileEntryNotFoundError,
    ProfileNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_eeo_self_identification_use_case,
    get_privacy_policy_version,
    get_profile_use_case,
    get_remove_education_entry_use_case,
    get_remove_skill_use_case,
    get_remove_work_history_entry_use_case,
    get_save_contact_details_use_case,
    get_save_education_entry_use_case,
    get_save_eeo_self_identification_use_case,
    get_save_skill_use_case,
    get_save_work_authorization_use_case,
    get_save_work_history_entry_use_case,
    get_update_education_standing_use_case,
    get_update_job_search_preferences_use_case,
    get_update_profile_address_use_case,
    get_update_profile_links_use_case,
    get_update_profile_qualifications_use_case,
    get_work_authorization_use_case,
)
from src.interfaces.http.schemas import (
    AddressRequest,
    ContactDetailsRequest,
    EducationRequest,
    EducationStandingRequest,
    EeoSelfIdentificationRequest,
    EeoSelfIdentificationResponse,
    JobSearchPreferencesRequest,
    ProfileLinksRequest,
    ProfileResponse,
    QualificationsRequest,
    SkillRequest,
    WorkAuthorizationRequest,
    WorkAuthorizationResponse,
    WorkHistoryRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/profile",
    tags=["profile"],
    dependencies=[Depends(get_current_user)],
)

#: The message a section returns when no profile exists yet. Names the remedy,
#: because "not found" on its own is not actionable — the candidate has to be told
#: that one specific section creates the profile.
_NO_PROFILE_DETAIL = (
    "You do not have a profile yet. Save your name and email first "
    "(PUT /api/profile/contact); that is the section that creates it."
)


def _profile_response(output: ProfileOutput) -> ProfileResponse:
    """Serialize the profile, nested sections and all.

    `asdict` rather than `__dict__`: the address, links and qualifications
    sections are nested dataclasses, and pydantic will not accept one where it
    expects its own model. `asdict` converts the whole tree, which is also what
    the résumé-parse response has always done with this DTO.
    """
    return ProfileResponse(**asdict(output))


# -- Reading ------------------------------------------------------------------


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetProfile = Depends(get_profile_use_case),
) -> ProfileResponse:
    """The authenticated user's whole profile, minus the EEO record."""
    try:
        output = await use_case.execute(user.subject)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    return _profile_response(output)


# -- Contact: the section that creates a profile -------------------------------


@router.put("/contact", response_model=ProfileResponse)
async def save_contact_details(
    request: ContactDetailsRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveContactDetails = Depends(get_save_contact_details_use_case),
) -> ProfileResponse:
    """Create or update the contact section.

    The only endpoint here that does not require an existing profile — it is what
    makes a résumé optional rather than the way in.

    Saving re-stamps the section as the candidate's own statement, so a profile
    that came from a résumé stops describing itself as parsed once they have
    confirmed it.
    """
    try:
        output = await use_case.execute(
            ContactDetailsInput(
                user_id=user.subject,
                full_name=request.full_name,
                email=request.email,
                phone=request.phone,
                headline=request.headline,
                location=request.location,
                middle_name=request.middle_name,
                preferred_name=request.preferred_name,
            )
        )
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Profile contact section saved for the authenticated user.")
    return _profile_response(output)


# -- The other non-sensitive sections ------------------------------------------


@router.put("/address", response_model=ProfileResponse)
async def update_address(
    request: AddressRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateProfileAddress = Depends(get_update_profile_address_use_case),
) -> ProfileResponse:
    """Replace the postal address. An all-empty body clears it."""
    try:
        output = await use_case.execute(
            AddressInput(
                user_id=user.subject,
                street_address=request.street_address,
                city=request.city,
                state_or_region=request.state_or_region,
                postal_code=request.postal_code,
                country=request.country,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    logger.info("Profile address section saved for the authenticated user.")
    return _profile_response(output)


@router.put("/links", response_model=ProfileResponse)
async def update_links(
    request: ProfileLinksRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateProfileLinks = Depends(get_update_profile_links_use_case),
) -> ProfileResponse:
    """Replace the portfolio/LinkedIn/GitHub links. An all-empty body clears them."""
    try:
        output = await use_case.execute(
            ProfileLinksInput(
                user_id=user.subject,
                portfolio_url=request.portfolio_url,
                linkedin_url=request.linkedin_url,
                github_url=request.github_url,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except InvalidValueError as exc:
        # `ProfileLinks` validates the URLs themselves.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Profile links section saved for the authenticated user.")
    return _profile_response(output)


@router.put("/qualifications", response_model=ProfileResponse)
async def update_qualifications(
    request: QualificationsRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateProfileQualifications = Depends(
        get_update_profile_qualifications_use_case
    ),
) -> ProfileResponse:
    """Replace the clearance level and highest degree — used for matching, not
    for filling forms. Empty clears either one."""
    try:
        output = await use_case.execute(
            QualificationsInput(
                user_id=user.subject,
                clearance_level=request.clearance_level,
                highest_degree=request.highest_degree,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Profile qualifications section saved for the authenticated user.")
    return _profile_response(output)


@router.put("/education-standing", response_model=ProfileResponse)
async def update_education_standing(
    request: EducationStandingRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateEducationStanding = Depends(get_update_education_standing_use_case),
) -> ProfileResponse:
    """Replace the candidate's current education standing.

    Separate from `/qualifications`, which records the highest *completed* degree.
    This one records what is in progress — the fact that lets a posting requiring
    a bachelor's accept a current undergraduate, and lets a graduate-student-only
    internship be filtered out for one.
    """
    try:
        output = await use_case.execute(
            EducationStandingInput(
                user_id=user.subject,
                enrollment_status=request.enrollment_status,
                degree_in_progress=request.degree_in_progress,
                expected_graduation=request.expected_graduation,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Profile education standing saved for the authenticated user.")
    return _profile_response(output)


@router.put("/job-search-preferences", response_model=ProfileResponse)
async def update_job_search_preferences(
    request: JobSearchPreferencesRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateJobSearchPreferences = Depends(
        get_update_job_search_preferences_use_case
    ),
) -> ProfileResponse:
    """Replace what kinds of role and which terms the candidate wants to see.

    Submitting empty lists clears the preferences, which is how filtering is
    turned back off — so this is a full replace, not a merge.
    """
    try:
        output = await use_case.execute(
            JobSearchPreferencesInput(
                user_id=user.subject,
                employment_types=tuple(request.employment_types),
                terms=tuple(
                    TermInput(season=term.season, year=term.year)
                    for term in request.terms
                ),
                functions=tuple(request.functions),
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Job-search preferences saved for the authenticated user.")
    return _profile_response(output)


# -- Work history --------------------------------------------------------------
#
# Add / edit / delete per entry rather than re-submitting the whole list, so an
# entry the résumé parser produced and the candidate never touched keeps its own
# provenance instead of being relabelled as something they typed.


@router.post(
    "/work-history",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_work_history(
    request: WorkHistoryRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveWorkHistoryEntry = Depends(get_save_work_history_entry_use_case),
) -> ProfileResponse:
    """Add a job. The id is server-generated."""
    return await _save_work_history(use_case, user, request, entry_id=None)


@router.put("/work-history/{entry_id}", response_model=ProfileResponse)
async def update_work_history(
    entry_id: str,
    request: WorkHistoryRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveWorkHistoryEntry = Depends(get_save_work_history_entry_use_case),
) -> ProfileResponse:
    """Replace one job. 404 when the id is not on the profile — a stale edit is
    refused rather than turned into a duplicate."""
    return await _save_work_history(use_case, user, request, entry_id=entry_id)


@router.delete("/work-history/{entry_id}", response_model=ProfileResponse)
async def remove_work_history(
    entry_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: RemoveWorkHistoryEntry = Depends(get_remove_work_history_entry_use_case),
) -> ProfileResponse:
    """Delete one job — including a duplicate a second résumé parse produced."""
    try:
        output = await use_case.execute(user.subject, entry_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    logger.info("Removed one work-history entry: %s", entry_id)
    return _profile_response(output)


async def _save_work_history(
    use_case: SaveWorkHistoryEntry,
    user: AuthenticatedUserDTO,
    request: WorkHistoryRequest,
    *,
    entry_id: str | None,
) -> ProfileResponse:
    try:
        output = await use_case.execute(
            WorkHistoryInput(
                user_id=user.subject,
                entry_id=entry_id,
                company_name=request.company_name,
                job_title=request.job_title,
                start_date=request.start_date,
                end_date=request.end_date,
                location=request.location,
                description=request.description,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidValueError as exc:
        # Dates that do not order, an empty company name after stripping.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Saved one work-history entry: %s", entry_id or "new")
    return _profile_response(output)


# -- Education -----------------------------------------------------------------


@router.post(
    "/education",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_education(
    request: EducationRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveEducationEntry = Depends(get_save_education_entry_use_case),
) -> ProfileResponse:
    return await _save_education(use_case, user, request, entry_id=None)


@router.put("/education/{entry_id}", response_model=ProfileResponse)
async def update_education(
    entry_id: str,
    request: EducationRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveEducationEntry = Depends(get_save_education_entry_use_case),
) -> ProfileResponse:
    return await _save_education(use_case, user, request, entry_id=entry_id)


@router.delete("/education/{entry_id}", response_model=ProfileResponse)
async def remove_education(
    entry_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: RemoveEducationEntry = Depends(get_remove_education_entry_use_case),
) -> ProfileResponse:
    try:
        output = await use_case.execute(user.subject, entry_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    logger.info("Removed one education entry: %s", entry_id)
    return _profile_response(output)


async def _save_education(
    use_case: SaveEducationEntry,
    user: AuthenticatedUserDTO,
    request: EducationRequest,
    *,
    entry_id: str | None,
) -> ProfileResponse:
    try:
        output = await use_case.execute(
            EducationInput(
                user_id=user.subject,
                entry_id=entry_id,
                institution_name=request.institution_name,
                degree=request.degree,
                majors=tuple(request.majors),
                minors=tuple(request.minors),
                start_date=request.start_date,
                end_date=request.end_date,
                description=request.description,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Saved one education entry: %s", entry_id or "new")
    return _profile_response(output)


# -- Skills --------------------------------------------------------------------


@router.post(
    "/skills", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED
)
async def add_skill(
    request: SkillRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveSkill = Depends(get_save_skill_use_case),
) -> ProfileResponse:
    return await _save_skill(use_case, user, request, entry_id=None)


@router.put("/skills/{skill_id}", response_model=ProfileResponse)
async def update_skill(
    skill_id: str,
    request: SkillRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveSkill = Depends(get_save_skill_use_case),
) -> ProfileResponse:
    return await _save_skill(use_case, user, request, entry_id=skill_id)


@router.delete("/skills/{skill_id}", response_model=ProfileResponse)
async def remove_skill(
    skill_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: RemoveSkill = Depends(get_remove_skill_use_case),
) -> ProfileResponse:
    try:
        output = await use_case.execute(user.subject, skill_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    logger.info("Removed one skill: %s", skill_id)
    return _profile_response(output)


async def _save_skill(
    use_case: SaveSkill,
    user: AuthenticatedUserDTO,
    request: SkillRequest,
    *,
    entry_id: str | None,
) -> ProfileResponse:
    try:
        output = await use_case.execute(
            SkillInput(
                user_id=user.subject,
                entry_id=entry_id,
                name=request.name,
                proficiency=request.proficiency,
                years_of_experience=request.years_of_experience,
            )
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except ProfileEntryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        # The duplicate-name rule. A 409 rather than a 422: the request is
        # well-formed and the name is fine — it is the profile's current contents
        # that make it a conflict.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    logger.info("Saved one skill: %s", entry_id or "new")
    return _profile_response(output)


# -- Work authorization: the section the whole apparatus was waiting for -------


@router.get("/work-authorization", response_model=WorkAuthorizationResponse)
async def get_work_authorization(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetWorkAuthorization = Depends(get_work_authorization_use_case),
) -> WorkAuthorizationResponse:
    """The stored legal declarations, with whether they are the candidate's own
    statement and whether consent is on record."""
    try:
        output = await use_case.execute(user.subject)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    return _work_authorization_response(output)


@router.put("/work-authorization", response_model=WorkAuthorizationResponse)
async def save_work_authorization(
    request: WorkAuthorizationRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveWorkAuthorization = Depends(get_save_work_authorization_use_case),
    policy_version: str = Depends(get_privacy_policy_version),
) -> WorkAuthorizationResponse:
    """Store the candidate's own work-authorization declarations.

    This is the endpoint that makes the sensitive-field machinery live: a record
    saved here is `USER_ENTERED`, therefore candidate-attested, therefore
    something `decide_sensitive_field` will actually put on a form.

    Requires `consent_acknowledged` — special-category data is stored only with
    an explicit affirmative act — and records the consent grant in the same
    request. `status: null` clears the record and needs no acknowledgement.

    The policy version comes from the deployment, never the body: a client that
    could assert which notice it had shown could record consent against a notice
    the candidate never saw.
    """
    try:
        output = await use_case.execute(
            WorkAuthorizationInput(
                user_id=user.subject,
                status=request.status,
                citizenship_country=request.citizenship_country,
                visa_type=request.visa_type,
                requires_sponsorship=request.requires_sponsorship,
                details=request.details,
                consent_acknowledged=request.consent_acknowledged,
            ),
            decided_at=datetime.now(UTC),
            policy_version=policy_version,
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except SensitiveStorageNotAcknowledgedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    # Counts and flags only — never the declarations themselves.
    logger.info(
        "Work authorization saved: stated=%s attested=%s",
        output.status is not None,
        output.is_candidate_attested,
    )
    return _work_authorization_response(output)


# -- EEO self-identification ---------------------------------------------------
#
# Its own two endpoints, deliberately not part of the profile payload. ApplyFlow
# never fills these answers onto an application; this exists so the candidate can
# see, correct and withdraw what is stored, and so the data export can include it.


@router.get("/eeo", response_model=EeoSelfIdentificationResponse)
async def get_eeo_self_identification(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetEeoSelfIdentification = Depends(get_eeo_self_identification_use_case),
) -> EeoSelfIdentificationResponse:
    """The stored voluntary self-identification, for the candidate's own view."""
    try:
        output = await use_case.execute(user.subject)
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    return _eeo_response(output)


@router.put("/eeo", response_model=EeoSelfIdentificationResponse)
async def save_eeo_self_identification(
    request: EeoSelfIdentificationRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SaveEeoSelfIdentification = Depends(
        get_save_eeo_self_identification_use_case
    ),
    policy_version: str = Depends(get_privacy_policy_version),
) -> EeoSelfIdentificationResponse:
    """Store the candidate's voluntary self-identification.

    Saving this changes nothing about what ApplyFlow puts on an application: EEO
    answers are refused unconditionally by `decide_sensitive_field` and stay the
    candidate's to give per application.

    Same acknowledgement and same consent purpose as work authorization. An
    all-empty body clears the record and needs no acknowledgement.
    """
    try:
        output = await use_case.execute(
            EeoSelfIdentificationInput(
                user_id=user.subject,
                gender_identity=request.gender_identity,
                race_ethnicity=request.race_ethnicity,
                veteran_status=request.veteran_status,
                disability_status=request.disability_status,
                consent_acknowledged=request.consent_acknowledged,
            ),
            decided_at=datetime.now(UTC),
            policy_version=policy_version,
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PROFILE_DETAIL) from exc
    except SensitiveStorageNotAcknowledgedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except UnknownProfileEnumValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    # Whether a record exists, never which categories were answered.
    logger.info("EEO self-identification saved: stated=%s", output.source is not None)
    return _eeo_response(output)


def _work_authorization_response(
    output: WorkAuthorizationOutput,
) -> WorkAuthorizationResponse:
    return WorkAuthorizationResponse(**output.__dict__)


def _eeo_response(
    output: EeoSelfIdentificationOutput,
) -> EeoSelfIdentificationResponse:
    return EeoSelfIdentificationResponse(**output.__dict__)
