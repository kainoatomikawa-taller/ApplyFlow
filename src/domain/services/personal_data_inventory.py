"""The personal-data inventory: every category of personal data ApplyFlow is
responsible for, and what the user's rights do to each one.

This module is the single source of truth for three things that otherwise drift
apart:

* **Export** (GDPR Art. 15/20, CCPA §1798.110/130) iterates the exportable
  categories. A category the inventory does not declare cannot appear in a
  portable copy, so a store nobody declared is a store nobody exports.
* **Erasure** (Art. 17, CCPA §1798.105) iterates the categories dispositioned
  `ERASE`. A category held elsewhere is reported as deferred with the name of
  whoever has to act, rather than silently omitted.
* **Notice at collection** — the `description` and `lawful_basis` on each
  category are what a privacy notice is written from. Keeping them next to the
  code that reads the data is what stops the notice from describing a product
  that no longer exists.

Two tests hold this honest, and both are the point of the file rather than
extras. `tests/infrastructure/test_personal_data_inventory_covers_schema.py`
walks `Base.metadata`, works out which tables carry data reachable from a user,
and fails if the set does not match the tables declared here — so adding a
user-scoped table forces an entry. The adapter-coverage half of the same file
fails if `PersonalDataStorePort`'s implementation does not handle a category
that needs handling. Adding a store without declaring it, or declaring one
without implementing it, both break the build.

What is deliberately *not* in the database
------------------------------------------
Three categories are declared with dispositions this codebase cannot execute,
and they are the ones a review would otherwise catch as missing:

* résumé bytes in the blob store — erasable here, but the export carries a
  manifest rather than the file, because a portable copy is a JSON document;
* prompts and embeddings sent to the model providers — they are processors, so
  erasure is a term in the agreement with them, not a call;
* the application a user submitted to an employer — the employer is an
  independent controller, and the user exercises their rights there directly.
  The export names the employers so they know where to go.

Single-user scale
-----------------
Today `user_id` is always the one provisioned account, so "erase the user's
data" and "empty the database" are nearly the same operation. The inventory is
built as though they are not, because the habits that make multi-user viable
are the ones that treat the subject as a parameter from the start — see
docs/decisions/0004-gdpr-ccpa-groundwork.md for what remains to be done when
that changes.
"""

from __future__ import annotations

from src.domain.exceptions import (
    InvalidValueError,
    UnknownPersonalDataCategoryError,
)
from src.domain.value_objects.lawful_basis import LawfulBasis
from src.domain.value_objects.personal_data_category import (
    ErasureDisposition,
    PersonalDataCategory,
    PersonalDataStore,
)


class PersonalDataInventory:
    """A validated set of personal-data categories, queryable by the export and
    erasure paths.

    A class rather than a bare tuple so the invariants hold at import time:
    duplicate keys, a table claimed by two categories, or an inventory with
    nothing erasable are all mistakes that would otherwise surface as a wrong
    export months later.
    """

    def __init__(self, categories: tuple[PersonalDataCategory, ...]) -> None:
        self._categories = categories
        self._validate()
        self._by_key = {category.key: category for category in categories}

    def _validate(self) -> None:
        if not self._categories:
            raise InvalidValueError("The personal-data inventory cannot be empty.")
        keys = [category.key for category in self._categories]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise InvalidValueError(
                f"Duplicate personal-data category keys: {sorted(duplicates)}."
            )
        # A table owned by two categories is the one arrangement that makes the
        # coverage test pass while the behaviour is wrong: an erasure would run
        # twice against it and an export would list its rows twice, and neither
        # is visible from the declaration alone.
        seen: dict[str, str] = {}
        for category in self._categories:
            for table in category.tables:
                if table in seen:
                    raise InvalidValueError(
                        f"Table '{table}' is claimed by both "
                        f"'{seen[table]}' and '{category.key}'; a table belongs "
                        "to exactly one category so export and erasure touch it "
                        "once."
                    )
                seen[table] = category.key
        if not any(category.is_erased_locally for category in self._categories):
            raise InvalidValueError(
                "An inventory with nothing erasable cannot honor an erasure "
                "request; at least one category must be dispositioned ERASE."
            )

    @property
    def categories(self) -> tuple[PersonalDataCategory, ...]:
        """Every declared category, in declaration order — which is the order
        an export lists them in, so it reads as the product does rather than
        alphabetically."""
        return self._categories

    def category(self, key: str) -> PersonalDataCategory:
        """The category with this key.

        Raises:
            UnknownPersonalDataCategoryError: if it is not declared. Never
                returns None: a caller on an export or erasure path that
                shrugged off a missing category would produce an incomplete
                answer to a legal request.
        """
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownPersonalDataCategoryError(key) from None

    def exportable(self) -> tuple[PersonalDataCategory, ...]:
        """The categories that go into a portable copy."""
        return tuple(c for c in self._categories if c.exportable)

    def erasable(self) -> tuple[PersonalDataCategory, ...]:
        """The categories this application deletes on an erasure request."""
        return tuple(c for c in self._categories if c.is_erased_locally)

    def retained_on_erasure(self) -> tuple[PersonalDataCategory, ...]:
        """The categories that survive an erasure request, for whatever reason —
        a legal basis, another party's responsibility, or nothing personal
        being there to begin with.

        This is what the erasure receipt reports alongside what was deleted. A
        receipt that lists only deletions invites the reader to assume the
        remainder is nothing.
        """
        return tuple(c for c in self._categories if not c.is_erased_locally)

    def needing_local_handler(self) -> tuple[PersonalDataCategory, ...]:
        """The categories `PersonalDataStorePort` has to implement."""
        return tuple(c for c in self._categories if c.needs_local_handler)

    def covered_tables(self) -> frozenset[str]:
        """Every database table the inventory accounts for — the set the schema
        coverage test compares against `Base.metadata`."""
        return frozenset(
            table for category in self._categories for table in category.tables
        )


#: Notes shared by the categories that describe one physical store, so the
#: reasoning is stated once rather than copied and allowed to diverge.
_PROCESSOR_NOTE = (
    "Held by a processor under contract, so erasure is a term of that "
    "agreement rather than an operation this application can perform. The path "
    "to honoring it: the model and embedding providers are configured for "
    "zero-retention/no-training use, and an erasure request is satisfied by "
    "that configuration plus the deletion of the inputs and outputs stored "
    "here. A deployment that turns retention on has to add a per-provider "
    "deletion call and report it in the erasure receipt."
)


PERSONAL_DATA_INVENTORY = PersonalDataInventory(
    (
        PersonalDataCategory(
            key="profile",
            description=(
                "Your profile: name, contact details, postal address, links, "
                "work history, education, skills, and — where you provided "
                "them — your work authorization and voluntary EEO "
                "self-identification."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            # Contract for the profile as a whole. The special-category parts
            # of it sit under EXPLICIT_CONSENT as their own consent purpose
            # (`SENSITIVE_ATTRIBUTE_STORAGE`), which is why they are not split
            # into a separate category here: they live in child tables of the
            # profile aggregate and are erased with it either way.
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=(
                "user_profiles",
                "work_history_entries",
                "education_entries",
                "skills",
                "work_authorizations",
                "eeo_self_identifications",
            ),
        ),
        PersonalDataCategory(
            key="resumes",
            description=(
                "Résumés you uploaded: the file's name, type and size, and the "
                "text extracted from it."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("resumes",),
        ),
        PersonalDataCategory(
            key="resume_files",
            description=(
                "The original résumé files themselves, as uploaded. Your "
                "export lists them with their size and type; the extracted "
                "text of each is included under 'resumes'."
            ),
            store=PersonalDataStore.FILE_STORAGE,
            lawful_basis=LawfulBasis.CONTRACT,
            # Exportable as a manifest, not as bytes: a portable copy is a JSON
            # document, and inlining a base64 PDF would make it unusable in the
            # tools a user would open it with. The bytes remain retrievable
            # through the résumé endpoints while the account exists — and they
            # are what `erase` actually deletes off disk.
            exportable=True,
            erasure=ErasureDisposition.ERASE,
        ),
        PersonalDataCategory(
            key="answer_memories",
            description=(
                "Answers you gave to application questions, kept so a later "
                "application can reuse them, together with the question text "
                "and its embedding."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONSENT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("answer_memories",),
        ),
        PersonalDataCategory(
            key="application_documents",
            description=(
                "The exact tailored résumés and cover letters produced for "
                "each job, kept verbatim as the record of what was sent."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("application_documents",),
        ),
        PersonalDataCategory(
            key="application_reviews",
            description=(
                "Application forms ApplyFlow filled for you and the answers "
                "you reviewed, revised, or confirmed on them."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("application_reviews",),
        ),
        PersonalDataCategory(
            key="portal_handoffs",
            description=(
                "Points where automation stopped and handed an application "
                "portal back to you, and the notes you left about resolving "
                "them."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("portal_handoffs",),
        ),
        PersonalDataCategory(
            key="tracked_applications",
            description=(
                "Applications you actually sent: the company, role, date, "
                "which documents went out, and the full status history."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("tracked_applications", "application_status_events"),
        ),
        PersonalDataCategory(
            key="job_match_feedback",
            description=(
                "Your thumbs-up/down reactions to ranked job matches, with the "
                "score you saw at the time."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            tables=("job_match_feedback",),
        ),
        PersonalDataCategory(
            key="legacy_applications",
            description=(
                "Applications recorded by the earliest version of ApplyFlow, "
                "which filed them under your email address rather than your "
                "account id."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.CONTRACT,
            exportable=True,
            erasure=ErasureDisposition.ERASE,
            # The one category keyed by email rather than by user id, which is
            # why `DataSubjectRef` carries both. A request from a token with no
            # email claim cannot reach these rows, and the export and the
            # receipt say so rather than reporting zero.
            tables=("job_applications",),
        ),
        PersonalDataCategory(
            key="consents",
            description=(
                "The record of the privacy choices you made: which purpose, "
                "granted or withdrawn, when, and against which version of the "
                "privacy notice."
            ),
            store=PersonalDataStore.PRIMARY_DATABASE,
            lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
            exportable=True,
            erasure=ErasureDisposition.RETAIN_LEGAL_BASIS,
            tables=("consent_decisions",),
            note=(
                "Retained after erasure, deliberately. GDPR Art. 7(1) requires "
                "this application to be able to demonstrate that consent was "
                "given — and, more to the point, that a withdrawal was "
                "honored; deleting the ledger would destroy the evidence that "
                "the erasure itself was lawful. What is kept is a purpose, a "
                "yes/no, a timestamp and a notice version against an account "
                "id: no name, address, document or answer. At multi-user scale "
                "the account id should become a one-way digest so the retained "
                "ledger stops being linkable to a person at all — see "
                "docs/decisions/0004-gdpr-ccpa-groundwork.md."
            ),
        ),
        PersonalDataCategory(
            key="application_logs",
            description=(
                "Operational logs of what the application did — requests, "
                "retries, failures."
            ),
            store=PersonalDataStore.LOG_SINK,
            lawful_basis=LawfulBasis.LEGITIMATE_INTEREST,
            exportable=False,
            erasure=ErasureDisposition.NO_PERSONAL_DATA_RETAINED,
            note=(
                "Personal data is kept out of logs by construction rather than "
                "removed from them afterwards: a process-wide redaction filter "
                "scrubs values that look like personal data, and a static "
                "guard fails the build if a log call site reads a field known "
                "to carry it (ADR 0003). So there is nothing here to export or "
                "erase. This is the category to revisit first if request-level "
                "access logging is ever added, because client IP addresses are "
                "personal data and are deliberately not redacted today."
            ),
        ),
        PersonalDataCategory(
            key="model_provider_processing",
            description=(
                "Text sent to the AI providers that draft your documents and "
                "index your answers — résumé text, profile facts, job "
                "descriptions, and application questions."
            ),
            store=PersonalDataStore.PROCESSOR,
            lawful_basis=LawfulBasis.CONSENT,
            exportable=False,
            erasure=ErasureDisposition.DELEGATED,
            note=_PROCESSOR_NOTE,
        ),
        PersonalDataCategory(
            key="employer_disclosures",
            description=(
                "Everything an employer received when you applied: the "
                "documents and the answers on that application."
            ),
            store=PersonalDataStore.THIRD_PARTY_CONTROLLER,
            lawful_basis=LawfulBasis.CONSENT,
            exportable=False,
            erasure=ErasureDisposition.DELEGATED,
            note=(
                "An employer that receives your application decides for itself "
                "what to do with it, which makes it an independent controller "
                "rather than ApplyFlow's processor: it cannot be instructed to "
                "delete, and your rights against it are exercised with the "
                "employer directly. What this application can do is tell you "
                "where to go — the 'tracked_applications' section of your "
                "export names every employer, role and date, which is the list "
                "those requests are written from. Erasing your ApplyFlow data "
                "does not withdraw an application you already sent."
            ),
        ),
    )
)
