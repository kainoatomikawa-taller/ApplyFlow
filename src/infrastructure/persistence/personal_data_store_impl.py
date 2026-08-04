"""SqlAlchemyPersonalDataStore — the adapter behind `PersonalDataStorePort`.

This is where "everything we hold about one person" becomes actual queries. It is
deliberately the only module in the codebase that knows all of them at once, and
it is organized around two tables of handlers keyed by the inventory's category
keys (`_READERS` and `_ERASURES`), so the correspondence between what is declared
and what is implemented is something you can read rather than infer.

Three properties are worth understanding before editing:

**Rows, not entities.** An export reads columns directly and serializes them
whole. Going through the repositories would export what the domain model exposes
rather than what is stored, and the gap between those two is precisely what GDPR
Art. 20 ("all personal data concerning him or her") does not allow. It also means
a column added to a table appears in the export automatically — the opposite
default from the entity route, and the safer one.

**Erasure order is fixed here, not by the caller.** `tracked_applications`
references `application_documents` with `ON DELETE RESTRICT`, so the tracker rows
have to go first; `application_status_events` and the profile's child tables
CASCADE, so they need no explicit delete. `_ERASURES` is an ordered mapping and
its insertion order *is* the execution order — foreign keys are this layer's
business, not the use case's.

**Blob files are deleted before the rows that name them.** The résumé bytes on
disk cannot join a database transaction, so one of the two orderings has to be
chosen deliberately. Files first: a failure then leaves metadata for a file that
is already gone, and a retry finishes the job (the storage delete is idempotent).
The reverse would leave the actual résumé on disk with nothing pointing at it — a
receipt claiming erasure over a file nobody will ever find to clean up.

Reads sensitive columns, so every call has to be inside an authorized decryption
scope (`src/infrastructure/security/sensitive_access.py`). The scope is opened by
the entry point, not here: an adapter that granted itself decryption would be the
exact hole that module exists to close.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, TypeAlias, cast

from sqlalchemy import CursorResult, Delete, Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    PersonalDataRecord,
)
from src.application.ports.file_storage_port import FileStoragePort
from src.application.ports.personal_data_store_port import PersonalDataStorePort
from src.infrastructure.persistence.job_application_repository_impl import (
    email_blind_index,
)
from src.infrastructure.persistence.models import (
    AnswerMemoryModel,
    ApplicationDocumentModel,
    ApplicationReviewModel,
    ApplicationStatusEventModel,
    ConsentDecisionModel,
    EducationModel,
    EeoSelfIdentificationModel,
    JobApplicationModel,
    JobMatchFeedbackModel,
    PortalHandoffModel,
    ResumeModel,
    SkillModel,
    TrackedApplicationModel,
    UserProfileModel,
    WorkAuthorizationModel,
    WorkHistoryModel,
)

#: A reader returns the SELECTs whose rows make up one category — several where a
#: category spans tables the export should present side by side (the profile and
#: its children, an application and its status history).
_Reader: TypeAlias = Callable[[DataSubjectRef], tuple[Select[Any], ...]]

#: An eraser returns the DELETEs for one category, in the order they must run
#: within it.
_Eraser: TypeAlias = Callable[[DataSubjectRef], tuple[Delete, ...]]

#: The category whose data lives in the blob store rather than in SQL, so it is
#: served by neither handler table. Named as a constant because three places have
#: to agree about it: the read path, the erase path, and `handled_categories`.
_BLOB_CATEGORY = "resume_files"


class SqlAlchemyPersonalDataStore(PersonalDataStorePort):
    """Reads and erases one person's data across Postgres and the blob store."""

    def __init__(self, session: AsyncSession, file_storage: FileStoragePort) -> None:
        self._session = session
        self._file_storage = file_storage

    def handled_categories(self) -> frozenset[str]:
        return frozenset(_READERS) | frozenset(_ERASURES) | {_BLOB_CATEGORY}

    async def read(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, tuple[PersonalDataRecord, ...]]:
        collected: dict[str, tuple[PersonalDataRecord, ...]] = {}
        for key in category_keys:
            if key == _BLOB_CATEGORY:
                collected[key] = await self._read_resume_file_manifest(subject)
                continue
            reader = _READERS.get(key)
            if reader is None:
                # Omitted from the result rather than reported as empty, so the
                # use case raises `PersonalDataCoverageError` instead of
                # delivering a copy with a silently missing section. The static
                # coverage test is what should have caught this first.
                continue
            records: list[PersonalDataRecord] = []
            for statement in reader(subject):
                result = await self._session.execute(statement)
                records.extend(_as_record(row) for row in result.scalars())
            collected[key] = tuple(records)
        return collected

    async def erase(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, int]:
        requested = set(category_keys)
        counts: dict[str, int] = {}

        # Blob store first, and outside the transaction it cannot join — see the
        # module docstring for why this ordering and not the other one.
        if _BLOB_CATEGORY in requested:
            counts[_BLOB_CATEGORY] = await self._erase_resume_files(subject)

        for key, eraser in _ERASURES.items():
            if key not in requested:
                continue
            erased = 0
            for statement in eraser(subject):
                # `AsyncSession.execute` is typed as returning `Result`, which
                # has no `rowcount`; a DELETE always yields a `CursorResult`,
                # which does. The cast is that fact, not a workaround — and the
                # count is what the erasure receipt reports, so it is worth
                # reading off the statement rather than counting rows first.
                result = cast(
                    "CursorResult[Any]", await self._session.execute(statement)
                )
                erased += result.rowcount or 0
            counts[key] = erased
        await self._session.commit()
        return counts

    async def _read_resume_file_manifest(
        self, subject: DataSubjectRef
    ) -> tuple[PersonalDataRecord, ...]:
        """The blob-store section of an export: one entry per stored file.

        A manifest rather than the bytes. A portable copy is a JSON document, and
        inlining base64 PDFs would make it unopenable in the tools someone would
        actually use — while the *content* of every résumé is already in the
        export, as the extracted text under the `resumes` category. What this adds
        is the part the text does not carry: that a file exists, what it was
        called, how big it is, and the opaque key it is stored under.
        """
        result = await self._session.execute(
            select(ResumeModel).where(ResumeModel.user_id == subject.user_id)
        )
        return tuple(
            {
                "resume_id": model.id,
                "storage_key": model.storage_key,
                "original_filename": model.original_filename,
                "content_type": model.content_type,
                "size_bytes": model.size_bytes,
                "note": (
                    "The text extracted from this file is included under the "
                    "'resumes' category. The bytes themselves are not inlined "
                    "in this document."
                ),
            }
            for model in result.scalars()
        )

    async def _erase_resume_files(self, subject: DataSubjectRef) -> int:
        """Delete the résumé bytes from the blob store.

        Reads the keys before anything deletes the rows that hold them, which is
        why this runs first rather than being folded into the résumé category:
        once `resumes` is gone there is nothing left that knows which files
        belonged to this person, and the bytes become unreachable rather than
        erased.
        """
        result = await self._session.execute(
            select(ResumeModel.storage_key).where(
                ResumeModel.user_id == subject.user_id
            )
        )
        keys = list(result.scalars())
        for storage_key in keys:
            await self._file_storage.delete(storage_key)
        return len(keys)


# -- Serialization ------------------------------------------------------------


def _as_record(model: Any) -> PersonalDataRecord:
    """Serialize one ORM row into a JSON-safe mapping of its columns.

    Reflection over the mapper rather than a hand-written projection per table,
    for one reason that outweighs the brevity: a column added to a table lands in
    the export by default. A hand-written projection would silently omit it, and
    "the export has been missing a field since two releases ago" is not a bug
    anyone finds by reading code.

    Encrypted columns arrive here already decrypted — the column types do that on
    load — so this sees plaintext, which is what an export needs and why the
    access scope is required.
    """
    return {
        column.key: _as_json_safe(getattr(model, column.key))
        for column in model.__mapper__.column_attrs
    }


def _as_json_safe(value: object) -> object:
    """Render a stored value in a form JSON can carry.

    Datetimes and dates become ISO 8601 strings, which is what "commonly used,
    machine-readable" means for a timestamp. Everything else this schema stores —
    strings, ints, bools, None, and the JSON columns, which are already
    dicts/lists of those — passes through unchanged.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


# -- Category handlers --------------------------------------------------------
#
# Keyed by the category keys declared in `PersonalDataInventory`. The static
# coverage test compares these keys against the inventory in both directions, so
# a declared category with no handler and a handler for a category nobody
# declared are each a build failure.


#: The profile aggregate's child tables. `WorkAuthorizationModel` and
#: `EeoSelfIdentificationModel` are in here deliberately: they are the
#: special-category tables, so omitting them would leave out of an export the
#: data the user is most entitled to see, and out of an erasure the data most
#: consequential to leave behind.
_PROFILE_CHILDREN: tuple[Any, ...] = (
    WorkHistoryModel,
    EducationModel,
    SkillModel,
    WorkAuthorizationModel,
    EeoSelfIdentificationModel,
)


def _profile_reads(subject: DataSubjectRef) -> tuple[Select[Any], ...]:
    """The profile aggregate, as rows.

    Each table is read on its own rather than through the relationships, so the
    export lists work history, education and skills as their own records instead
    of nesting them inside the profile. A flat section per table is what a
    recipient can diff, and it matches how the data is actually stored. Reaching
    the children through a subquery on the profile id rather than a join also
    keeps the (encrypted) profile columns from being repeated on every child row.
    """
    profile_ids = select(UserProfileModel.id).where(
        UserProfileModel.user_id == subject.user_id
    )
    return (
        select(UserProfileModel).where(UserProfileModel.user_id == subject.user_id),
        *(
            select(child).where(child.profile_id.in_(profile_ids))
            for child in _PROFILE_CHILDREN
        ),
    )


def _reads_by_user_id(model: Any) -> _Reader:
    """A reader for a table keyed directly on `user_id` — most of them."""

    def read(subject: DataSubjectRef) -> tuple[Select[Any], ...]:
        return (select(model).where(model.user_id == subject.user_id),)

    return read


def _tracked_application_reads(subject: DataSubjectRef) -> tuple[Select[Any], ...]:
    """Sent applications and their status history.

    The history is its own section rather than nested — same reasoning as the
    profile's children — and it has to be reached through the application ids
    because `application_status_events` has no `user_id` of its own; it is keyed
    by the application it belongs to.
    """
    application_ids = select(TrackedApplicationModel.id).where(
        TrackedApplicationModel.user_id == subject.user_id
    )
    return (
        select(TrackedApplicationModel).where(
            TrackedApplicationModel.user_id == subject.user_id
        ),
        select(ApplicationStatusEventModel).where(
            ApplicationStatusEventModel.tracked_application_id.in_(application_ids)
        ),
    )


def _legacy_application_reads(subject: DataSubjectRef) -> tuple[Select[Any], ...]:
    """The pre-account applications, matched by blind index.

    `job_applications` files rows under the candidate's address, and that column
    is encrypted with a randomized cipher, so `WHERE candidate_email = ?` can
    never match. The blind index is the only thing that can — see
    `email_blind_index`.

    A subject with no email reaches nothing, and returns no statements rather
    than a predicate that would match every row in the table. The use case
    reports that as a stated limitation on the export, because an empty section
    would read as "you had none".
    """
    if not subject.email:
        return ()
    return (
        select(JobApplicationModel).where(
            JobApplicationModel.candidate_email_bidx == email_blind_index(subject.email)
        ),
    )


def _profile_erasures(subject: DataSubjectRef) -> tuple[Delete, ...]:
    """Delete the profile; the child tables CASCADE.

    Not spelled out as five more deletes: the foreign keys on
    `work_history_entries`/`education_entries`/`skills`/`work_authorizations`/
    `eeo_self_identifications` are all `ON DELETE CASCADE`, so listing them would
    duplicate what the database already guarantees — and drift from it if one
    were ever changed. The count reported for this category is therefore profile
    rows; the child rows go with them.
    """
    return (
        delete(UserProfileModel).where(UserProfileModel.user_id == subject.user_id),
    )


def _tracked_application_erasures(subject: DataSubjectRef) -> tuple[Delete, ...]:
    """Delete sent applications; their status events CASCADE.

    Must run before `application_documents`, whose rows this table references
    with `ON DELETE RESTRICT` — which is what `_ERASURES`' ordering encodes.
    """
    return (
        delete(TrackedApplicationModel).where(
            TrackedApplicationModel.user_id == subject.user_id
        ),
    )


def _erasures_by_user_id(model: Any) -> _Eraser:
    def erase(subject: DataSubjectRef) -> tuple[Delete, ...]:
        return (delete(model).where(model.user_id == subject.user_id),)

    return erase


def _legacy_application_erasures(subject: DataSubjectRef) -> tuple[Delete, ...]:
    if not subject.email:
        return ()
    return (
        delete(JobApplicationModel).where(
            JobApplicationModel.candidate_email_bidx == email_blind_index(subject.email)
        ),
    )


#: Read handler per category. `resume_files` is absent: its section comes from
#: the blob-store manifest, not from a SELECT.
_READERS: dict[str, _Reader] = {
    "profile": _profile_reads,
    "resumes": _reads_by_user_id(ResumeModel),
    "answer_memories": _reads_by_user_id(AnswerMemoryModel),
    "application_documents": _reads_by_user_id(ApplicationDocumentModel),
    "application_reviews": _reads_by_user_id(ApplicationReviewModel),
    "portal_handoffs": _reads_by_user_id(PortalHandoffModel),
    "tracked_applications": _tracked_application_reads,
    "job_match_feedback": _reads_by_user_id(JobMatchFeedbackModel),
    "legacy_applications": _legacy_application_reads,
    "consents": _reads_by_user_id(ConsentDecisionModel),
}


#: Erasure handler per category, in the order they must run. Insertion order is
#: the execution order, so the two cannot disagree: `tracked_applications` before
#: `application_documents` is a `RESTRICT` foreign key, not a preference.
#:
#: `consents` is deliberately absent. The inventory retains that ledger as the
#: record that the erasure was lawful (GDPR Art. 7(1)), and an adapter capable of
#: deleting it would be one mistaken `category_keys` away from destroying exactly
#: that. The capability is not offered rather than merely unused.
_ERASURES: dict[str, _Eraser] = {
    "tracked_applications": _tracked_application_erasures,
    "application_documents": _erasures_by_user_id(ApplicationDocumentModel),
    "application_reviews": _erasures_by_user_id(ApplicationReviewModel),
    "portal_handoffs": _erasures_by_user_id(PortalHandoffModel),
    "answer_memories": _erasures_by_user_id(AnswerMemoryModel),
    "job_match_feedback": _erasures_by_user_id(JobMatchFeedbackModel),
    "resumes": _erasures_by_user_id(ResumeModel),
    "profile": _profile_erasures,
    "legacy_applications": _legacy_application_erasures,
}
