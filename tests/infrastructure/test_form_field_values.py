"""Tests for how a caller's string value maps onto an HTML form control.

Pure value semantics — no browser involved. These cover the decisions that
must never drift, because the harness applies them to real job
applications: a checkbox only ticks on something that actually means yes,
and a select only accepts an option it can name exactly.
"""

from __future__ import annotations

import pytest

from src.application.ports.browser_automation_port import FormFieldOption
from src.infrastructure.browser_automation.field_values import (
    describe_options,
    interpret_boolean,
    match_option,
    matches_own_value,
    normalize,
)

_COUNTRIES = (
    FormFieldOption(label="United States", value="us"),
    FormFieldOption(label="Canada", value="ca"),
    FormFieldOption(label="United Kingdom", value="uk"),
)


@pytest.mark.parametrize(
    "value", ["true", "TRUE", "yes", "Y", "1", "on", "checked", " x "]
)
def test_boolean_true_forms(value: str):
    assert interpret_boolean(value) is True


@pytest.mark.parametrize(
    "value", ["false", "No", "n", "0", "off", "unchecked", "", "   "]
)
def test_boolean_false_forms(value: str):
    assert interpret_boolean(value) is False


@pytest.mark.parametrize("value", ["United States", "maybe", "2", "si"])
def test_boolean_is_none_when_the_value_is_not_a_yes_or_no(value: str):
    """`None` is a real answer, not a failure: the caller may have meant to
    tick a box named after the value (see matches_own_value)."""
    assert interpret_boolean(value) is None


def test_checkbox_can_be_named_by_its_own_label():
    assert matches_own_value(
        value="United States", own_value="us", label="United States"
    )


def test_checkbox_can_be_named_by_its_submitted_value():
    assert matches_own_value(value="us", own_value="us", label="United States")


def test_checkbox_name_match_ignores_case_and_spacing():
    assert matches_own_value(
        value="  united   states ", own_value="us", label="United States"
    )


def test_checkbox_name_match_rejects_an_unrelated_value():
    assert not matches_own_value(value="Mexico", own_value="us", label="United States")


def test_checkbox_name_match_never_succeeds_on_an_empty_value():
    """An empty value must not match a field whose own value is also empty
    -- that would tick a box nobody asked to tick."""
    assert not matches_own_value(value="", own_value="", label="")


def test_option_matched_by_exact_submitted_value():
    assert match_option(_COUNTRIES, "ca") == FormFieldOption(label="Canada", value="ca")


def test_option_matched_by_exact_label():
    assert match_option(_COUNTRIES, "United Kingdom") == FormFieldOption(
        label="United Kingdom", value="uk"
    )


def test_option_matched_by_normalized_label():
    assert match_option(_COUNTRIES, "  united states  ") == FormFieldOption(
        label="United States", value="us"
    )


def test_exact_value_match_wins_over_an_exact_label_match():
    """When one option's submitted value equals another's label, the value
    hit is the less ambiguous reading of what the caller asked for."""
    options = (
        FormFieldOption(label="Remote", value="Onsite"),
        FormFieldOption(label="Onsite", value="onsite-2"),
    )
    assert match_option(options, "Onsite") == options[0]


def test_option_not_matched_by_a_near_miss():
    """No fuzzy matching, ever: "United" resembles two options, and picking
    either would submit an answer the candidate never gave."""
    assert match_option(_COUNTRIES, "United") is None


def test_option_not_matched_by_a_prefix_or_substring():
    assert match_option(_COUNTRIES, "Canada (remote)") is None
    assert match_option(_COUNTRIES, "can") is None


def test_no_options_matches_nothing():
    assert match_option((), "us") is None


def test_describe_options_lists_labels_for_an_error_message():
    assert describe_options(_COUNTRIES) == (
        "'United States', 'Canada', 'United Kingdom'"
    )


def test_describe_options_falls_back_to_values_for_unlabelled_options():
    options = (FormFieldOption(label="", value="us"),)
    assert describe_options(options) == "'us'"


def test_describe_options_says_so_when_there_are_none():
    assert describe_options(()) == "no options"


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  United\n  STATES  ") == "united states"


# ---- The yes/no legal questions ---------------------------------------------

#: How the sensitive-field policy's "Yes"/"No" answers meet a real portal.
_PLAIN_YES_NO = (
    FormFieldOption(label="Yes", value="1"),
    FormFieldOption(label="No", value="0"),
)
_SENTENCE_YES_NO = (
    FormFieldOption(label="Yes, I am authorized to work in the US", value="1"),
    FormFieldOption(label="No, I will require sponsorship", value="0"),
)


@pytest.mark.parametrize("answer", ["Yes", "No", "yes", " NO "])
def test_a_yes_no_answer_matches_a_plainly_labelled_option(answer):
    """The common case: `decide_sensitive_field` produces bare "Yes"/"No" and
    that is how these options are labelled across Greenhouse, Lever, and
    Ashby."""
    matched = match_option(_PLAIN_YES_NO, answer)
    assert matched is not None
    assert matched.label.strip().casefold() == answer.strip().casefold()


@pytest.mark.parametrize("answer", ["Yes", "No"])
def test_a_yes_no_answer_is_refused_when_the_portal_writes_sentences(answer):
    """ "Yes" does not match "Yes, I am authorized to work in the US", and must
    not: on a work-authorization question, selecting the option that merely
    starts with the right word is how a candidate ends up declaring something
    they never said. The refusal hands back the real options instead."""
    assert match_option(_SENTENCE_YES_NO, answer) is None
    assert "Yes, I am authorized to work in the US" in describe_options(
        _SENTENCE_YES_NO
    )
