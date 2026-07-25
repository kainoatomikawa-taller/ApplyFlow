"""Tests for the shared ATS section-heading vocabulary.

Three services read from this one definition, so the property worth pinning
is that they all agree — a heading the formatter treats as structural is the
same one the validator accepts and the parser splits on.
"""

from __future__ import annotations

from src.domain.services.ats_safe_text_formatter import AtsSafeTextFormatter
from src.domain.services.ats_safety_validator import (
    RULE_NON_STANDARD_HEADING,
    AtsSafetyValidator,
)
from src.domain.services.ats_section_headings import (
    STANDARD_SECTION_HEADINGS,
    is_standard_section_heading,
    normalize_heading,
)
from src.domain.services.resume_structure_parser import ResumeStructureParser


def test_the_standard_headings_are_recognized():
    for heading in ("EXPERIENCE", "Education", "skills", "Professional Summary"):
        assert is_standard_section_heading(heading), heading


def test_an_unrecognized_heading_is_not():
    for heading in ("CAREER HIGHLIGHTS", "Random Section", "About Me"):
        assert not is_standard_section_heading(heading), heading


def test_casing_colons_and_surrounding_space_do_not_matter():
    for variant in ("EXPERIENCE", "experience", " Experience: ", "Experience:"):
        assert is_standard_section_heading(variant), variant


def test_normalization_produces_the_key_the_set_is_defined_on():
    assert normalize_heading(" Technical Skills: ") == "technical skills"
    assert normalize_heading("EXPERIENCE") in STANDARD_SECTION_HEADINGS


def test_every_standard_heading_is_stored_already_normalized():
    """A heading stored with stray case or a colon would never match."""
    for heading in STANDARD_SECTION_HEADINGS:
        assert normalize_heading(heading) == heading


def test_all_three_services_agree_on_what_counts_as_a_heading():
    """The reason this vocabulary is shared: with per-service copies, one
    service's heading becomes another's prose."""
    validator = AtsSafetyValidator()
    parser = ResumeStructureParser()
    formatter = AtsSafeTextFormatter()

    for heading in sorted(STANDARD_SECTION_HEADINGS):
        printed = heading.upper()
        content = f"Dana Reyes\n\n{printed}\nSome content"

        # The validator does not flag it as unrecognized...
        assert RULE_NON_STANDARD_HEADING not in validator.validate(content).broken_rules
        # ...the parser splits on it...
        assert parser.parse(content).headings == (printed,)
        # ...and the formatter drops it when its body is gone.
        assert printed not in formatter.drop_empty_sections(f"Dana Reyes\n\n{printed}")
