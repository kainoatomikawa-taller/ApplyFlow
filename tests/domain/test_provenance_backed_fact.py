"""Tests for ProvenanceBackedFact — a fact that cannot exist without the
provenance that entitles ApplyFlow to assert it.
"""

from __future__ import annotations

import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact
from src.domain.value_objects.provenance_source import ProvenanceSource


def test_a_fact_carries_its_text_and_source():
    fact = ProvenanceBackedFact(
        text="Skill: Python", source=ProvenanceSource.PARSED_RESUME
    )

    assert fact.text == "Skill: Python"
    assert fact.source is ProvenanceSource.PARSED_RESUME


def test_blank_text_is_rejected():
    with pytest.raises(InvalidValueError):
        ProvenanceBackedFact(text="   ", source=ProvenanceSource.USER_ENTERED)


def test_a_raw_string_source_is_rejected():
    """The source has to be a real `ProvenanceSource`, not a lookalike
    string — otherwise "provenance-backed" means nothing."""
    with pytest.raises(InvalidValueError):
        ProvenanceBackedFact(text="Skill: Python", source="parsed_resume")  # type: ignore[arg-type]


def test_a_missing_source_is_rejected():
    with pytest.raises(InvalidValueError):
        ProvenanceBackedFact(text="Skill: Python", source=None)  # type: ignore[arg-type]


def test_facts_are_compared_by_value():
    first = ProvenanceBackedFact(
        text="Skill: Python", source=ProvenanceSource.PARSED_RESUME
    )
    second = ProvenanceBackedFact(
        text="Skill: Python", source=ProvenanceSource.PARSED_RESUME
    )

    assert first == second
    assert len({first, second}) == 1
