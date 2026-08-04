"""DTOs for the data-subject rights use cases: export, erasure, and consent.

Two things about the shapes here are deliberate and worth reading before
changing them.

**The export carries its own explanation.** Every section names the lawful
basis it is held under, and the deferred sections say who has to act and how.
That is not padding: a portable copy that is only rows is a copy the recipient
cannot check, and the categories this application *cannot* erase are precisely
the ones a user needs told about. The document is meant to be complete enough
to answer a subject access request on its own.

**The erasure receipt reports what survived.** `ErasureOutput` has a `retained`
list beside its `erased` list, for the same reason: a receipt that lists only
deletions invites the reader to conclude the remainder was nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

#: One stored record, as column-name -> JSON-safe value. Deliberately loose:
#: this is the payload of a portable copy, whose whole purpose is to carry
#: everything stored rather than a shape the application layer has opinions
#: about. Typing it as an entity would be typing it as *less* than what GDPR
#: Art. 20 requires — "all personal data concerning him or her", not the subset
#: the domain model happens to expose. It is the one place in this codebase
#: where an open mapping is the correct contract rather than a shortcut around
#: one, and it lives here (with the DTOs) rather than on the port so the port
#: can depend on this module without the two importing each other.
PersonalDataRecord = Mapping[str, object]


@dataclass(frozen=True)
class DataSubjectRef:
    """Who a data-rights request is about.

    Carries the email as well as the account id because one store predates the
    account model: `job_applications` files rows under the candidate's address
    (see the `legacy_applications` category). Every other store keys on
    `user_id`, and new ones should.

    `email` is optional because the verified token may not carry the claim. A
    request from such a token cannot reach the legacy rows, and the export and
    the receipt say so explicitly rather than reporting zero — a zero would
    read as "there were none".
    """

    user_id: str
    email: str | None = None


@dataclass(frozen=True)
class ExportedCategoryOutput:
    """One section of a portable copy: what it is, why it is held, and the
    records themselves."""

    key: str
    description: str
    store: str
    lawful_basis: str
    record_count: int
    records: tuple[PersonalDataRecord, ...]


@dataclass(frozen=True)
class DeferredCategoryOutput:
    """A category that is *not* in the portable copy, or not erased by this
    application — with the reason and whoever has to act.

    Present in both the export and the erasure receipt on purpose. These are
    the gaps in a compliance story, and a story that omits its gaps is the
    failure this work exists to avoid.
    """

    key: str
    description: str
    store: str
    lawful_basis: str
    disposition: str
    note: str


@dataclass(frozen=True)
class ConsentStateOutput:
    """One purpose and where it stands.

    `granted` is the answer to act on; `decided` says whether the user has ever
    been asked, which is a different question. A purpose that is
    `granted=True, decided=False` is one permitted by default because it is not
    consent-based — reading `granted` alone would make that look like an answer
    the user gave.
    """

    purpose: str
    description: str
    lawful_basis: str
    granted: bool
    decided: bool
    withdrawable: bool
    decided_at: datetime | None
    policy_version: str | None


@dataclass(frozen=True)
class ConsentDecisionOutput:
    """One entry in the consent ledger — the demonstration record."""

    purpose: str
    granted: bool
    decided_at: datetime
    policy_version: str


@dataclass(frozen=True)
class PersonalDataExportOutput:
    """A complete, portable copy of one person's data.

    `format_version` is the schema of this document, not of the privacy notice.
    A recipient parsing an export needs to know when its shape changes, and the
    notice version (`consent_policy_version`) answers a different question.
    """

    format_version: str
    subject_user_id: str
    generated_at: datetime
    consent_policy_version: str | None
    categories: tuple[ExportedCategoryOutput, ...]
    deferred_categories: tuple[DeferredCategoryOutput, ...]
    consents: tuple[ConsentStateOutput, ...]
    consent_history: tuple[ConsentDecisionOutput, ...]
    #: Non-fatal completeness caveats — today, the one case where a request
    #: carries no email claim and so cannot reach the legacy rows. Stated in
    #: the document rather than logged, because the person holding the export
    #: is the one who needs to know it may be short.
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ErasureRequestInput:
    """A request to erase everything erasable about one person.

    `acknowledged` has to be True. Erasure is irreversible and total, and a
    use case that would run it on an empty request body is one an accidental
    POST can trigger. The interface layer is free to ask for a stronger
    confirmation on top; this is the floor, and it is enforced here so the CLI
    and any future adapter inherit it rather than each remembering.
    """

    subject: DataSubjectRef
    requested_at: datetime
    acknowledged: bool
    #: The privacy-notice version in force, recorded on the withdrawal
    #: decisions the erasure writes to the consent ledger before deleting.
    policy_version: str
    #: Free text from the requester, kept out of storage — it exists so an
    #: operator running this from the CLI can say why in the receipt they keep.
    reason: str = ""


@dataclass(frozen=True)
class ErasedCategoryOutput:
    """One category the erasure actually deleted, and how much."""

    key: str
    description: str
    store: str
    records_erased: int


@dataclass(frozen=True)
class ErasureOutput:
    """The receipt for an erasure request."""

    subject_user_id: str
    executed_at: datetime
    erased: tuple[ErasedCategoryOutput, ...]
    retained: tuple[DeferredCategoryOutput, ...]
    #: Purposes whose consent was withdrawn as part of this erasure. Recorded
    #: before the deletion, so the retained ledger shows the request being
    #: honored rather than an account that simply stopped existing.
    consents_withdrawn: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    @property
    def total_records_erased(self) -> int:
        return sum(category.records_erased for category in self.erased)


@dataclass(frozen=True)
class RecordConsentInput:
    """One consent decision to record."""

    user_id: str
    #: The purpose's stable value (`ConsentPurpose`). A string rather than the
    #: enum so the interface layer can hand over what arrived on the wire and
    #: let the use case reject an unknown one, instead of every adapter
    #: reimplementing the parse.
    purpose: str
    granted: bool
    decided_at: datetime
    policy_version: str


@dataclass(frozen=True)
class RecordConsentOutput:
    """The resulting state, plus whether anything actually changed.

    `changed` is False when the decision restated what the ledger already said
    — a client re-sending the state of a toggle it already rendered. The caller
    gets to report "already set" without diffing, and the ledger stays a record
    of decisions rather than of clicks.
    """

    state: ConsentStateOutput
    changed: bool
