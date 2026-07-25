"""Tests for ApplicationDocument — an immutable snapshot of what was
actually produced for a job.

The behavior under test is not "does it hold two strings" but "can what was
sent be quietly changed, lost, or misnumbered".
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from src.domain.entities.application_document import ApplicationDocument
from src.domain.exceptions import DocumentSnapshotIntegrityError, InvalidValueError
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource

_CONTENT = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"


def _document(**overrides) -> ApplicationDocument:
    defaults = {
        "id": "doc-1",
        "user_id": "user-1",
        "job_posting_id": "job-1",
        "document_kind": GeneratedDocumentKind.TAILORED_RESUME,
        "content": _CONTENT,
        "version": 1,
        "backing_sources": (ProvenanceSource.PARSED_RESUME,),
    }
    defaults.update(overrides)
    return ApplicationDocument(**defaults)


# ---- immutability ------------------------------------------------------------


def test_a_stored_document_cannot_be_rewritten():
    document = _document()

    with pytest.raises(FrozenInstanceError):
        document.content = "Staff Engineer at Initech"  # type: ignore[misc]


def test_no_field_of_a_snapshot_can_be_reassigned():
    """Not just the content: the job it was sent for and the version that
    identifies it are equally part of the record."""
    document = _document()

    for field_name, value in (
        ("job_posting_id", "job-2"),
        ("version", 9),
        ("created_at", datetime(2020, 1, 1, tzinfo=UTC)),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(document, field_name, value)


def test_backing_sources_must_be_a_tuple_so_the_entity_is_really_frozen():
    """A list field would be mutable inside a frozen entity."""
    with pytest.raises(InvalidValueError):
        _document(backing_sources=[ProvenanceSource.PARSED_RESUME])


# ---- integrity --------------------------------------------------------------


def test_the_digest_identifies_the_exact_content():
    """Down to a trailing space: a snapshot's premise is byte-level."""
    assert _document().content_sha256 == _document(content=_CONTENT).content_sha256
    assert (
        _document().content_sha256 != _document(content=_CONTENT + " ").content_sha256
    )


def test_content_matching_its_recorded_digest_is_accepted():
    document = _document()

    document.ensure_content_matches(document.content_sha256)


def test_content_that_changed_after_it_was_written_is_refused():
    """Stands in for a row edited by a migration or a manual UPDATE: the
    digest recorded at write time no longer describes the content."""
    document = _document()
    digest_of_something_else = _document(content="Different text").content_sha256

    with pytest.raises(DocumentSnapshotIntegrityError) as exc_info:
        document.ensure_content_matches(digest_of_something_else)

    assert exc_info.value.document_id == "doc-1"
    # The failure is debuggable from digests alone — the content is sensitive
    # and must not travel in an exception message.
    assert _CONTENT not in str(exc_info.value)


# ---- versioning -------------------------------------------------------------


def test_the_first_snapshot_for_a_job_is_version_one():
    document = ApplicationDocument.snapshot(
        document_id="doc-1",
        user_id="user-1",
        job_posting_id="job-1",
        document_kind=GeneratedDocumentKind.COVER_LETTER,
        content="I led a team of 5 engineers.",
        backing_sources=(ProvenanceSource.ANSWER,),
    )

    assert document.version == 1


def test_regenerating_for_the_same_job_takes_the_next_version():
    document = ApplicationDocument.snapshot(
        document_id="doc-4",
        user_id="user-1",
        job_posting_id="job-1",
        document_kind=GeneratedDocumentKind.COVER_LETTER,
        content="I led a team of 5 engineers.",
        backing_sources=(ProvenanceSource.ANSWER,),
        stored_versions=3,
    )

    assert document.version == 4


def test_a_negative_stored_count_is_rejected_rather_than_numbered_from():
    with pytest.raises(InvalidValueError):
        ApplicationDocument.snapshot(
            document_id="doc-1",
            user_id="user-1",
            job_posting_id="job-1",
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content="I led a team of 5 engineers.",
            backing_sources=(ProvenanceSource.ANSWER,),
            stored_versions=-1,
        )


def test_versions_below_one_are_rejected():
    with pytest.raises(InvalidValueError):
        _document(version=0)


# ---- invariants -------------------------------------------------------------


@pytest.mark.parametrize("field_name", ["id", "user_id", "job_posting_id"])
def test_an_unidentifiable_snapshot_is_rejected(field_name):
    with pytest.raises(InvalidValueError):
        _document(**{field_name: ""})


def test_an_empty_document_is_not_a_snapshot_of_anything():
    with pytest.raises(InvalidValueError):
        _document(content="   \n  ")


def test_a_document_with_no_backing_provenance_is_never_stored_as_sent():
    """The generation flows refuse to return unattested content
    (`UnattestedGenerationError`); the store refuses to hold it either, so
    the two cannot disagree about what counts as a real document."""
    with pytest.raises(InvalidValueError):
        _document(backing_sources=())


def test_backing_sources_must_be_provenance_members_not_bare_strings():
    with pytest.raises(InvalidValueError):
        _document(backing_sources=("parsed_resume",))


def test_the_document_kind_must_be_a_known_kind():
    with pytest.raises(InvalidValueError):
        _document(document_kind="tailored_resume")


def test_a_snapshot_says_which_kind_of_document_it_holds():
    resume = _document()
    letter = _document(document_kind=GeneratedDocumentKind.COVER_LETTER)

    assert resume.is_tailored_resume and not resume.is_cover_letter
    assert letter.is_cover_letter and not letter.is_tailored_resume
