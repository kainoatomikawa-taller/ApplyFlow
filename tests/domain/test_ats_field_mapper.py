"""Recognition tests for `recognize_application_field`.

The field shapes below are the ones the three supported platforms actually
serve — bracketed Greenhouse names, Lever's `org`/`urls[...]`, Ashby's
`_systemfield_*` ids — so a change to the tables or the rule order shows up
here as a concrete form breaking rather than as an abstract mapping change.
"""

import pytest

from src.domain.services.ats_field_mapper import recognize_application_field
from src.domain.value_objects.application_field_slot import ApplicationFieldSlot
from src.domain.value_objects.ats_form_question import AtsFormQuestion
from src.domain.value_objects.ats_provider import AtsProvider

Slot = ApplicationFieldSlot


def recognize(
    label: str = "",
    *,
    provider: AtsProvider = AtsProvider.GREENHOUSE,
    name: str = "",
    element_id: str = "",
    autocomplete: str = "",
) -> ApplicationFieldSlot | None:
    return recognize_application_field(
        AtsFormQuestion(
            label=label,
            control_name=name,
            element_id=element_id,
            autocomplete=autocomplete,
        ),
        provider=provider,
    )


# ---- Greenhouse --------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "label", "expected"),
    [
        ("job_application[first_name]", "First Name *", Slot.FIRST_NAME),
        ("job_application[last_name]", "Last Name *", Slot.LAST_NAME),
        ("job_application[email]", "Email *", Slot.EMAIL),
        ("job_application[phone]", "Phone", Slot.PHONE),
        ("job_application[resume]", "Resume/CV *", Slot.RESUME),
        ("job_application[cover_letter]", "Cover Letter", Slot.COVER_LETTER),
        ("job_application[location]", "Location (City)", Slot.LOCATION),
    ],
)
def test_greenhouse_standard_fields_are_recognized(name, label, expected):
    assert recognize(label, provider=AtsProvider.GREENHOUSE, name=name) is expected


@pytest.mark.parametrize(
    ("name", "label", "expected"),
    [
        (
            "job_application[educations][][school_name_id]",
            "School",
            Slot.SCHOOL,
        ),
        ("job_application[educations][][degree_id]", "Degree", Slot.DEGREE),
        (
            "job_application[educations][][discipline_id]",
            "Discipline",
            Slot.FIELD_OF_STUDY,
        ),
        (
            "job_application[educations][][start_date]",
            "Start Date",
            Slot.EDUCATION_START_DATE,
        ),
        (
            "job_application[educations][][end_date]",
            "End Date",
            Slot.EDUCATION_END_DATE,
        ),
    ],
)
def test_greenhouse_education_block_is_recognized_through_its_nesting(
    name, label, expected
):
    assert recognize(label, provider=AtsProvider.GREENHOUSE, name=name) is expected


def test_a_bare_date_label_outside_an_education_block_is_not_recognized():
    """ "End Date" alone could belong to an employment block just as easily,
    and the label cannot tell them apart — so only the nested control name
    resolves it (see the education note in `_LABEL_RULES`)."""
    assert recognize("End Date", provider=AtsProvider.GREENHOUSE) is None
    assert recognize("Start Date", name="end_date") is None


def test_a_greenhouse_custom_question_is_not_recognized():
    """A company's own screening question is exactly what must be surfaced
    rather than answered."""
    assert (
        recognize(
            "Why do you want to work at Globex?",
            provider=AtsProvider.GREENHOUSE,
            name="job_application[answers_attributes][0][text_value]",
        )
        is None
    )


# ---- Lever -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "label", "expected"),
    [
        ("name", "Full name✱", Slot.FULL_NAME),
        ("email", "Email✱", Slot.EMAIL),
        ("phone", "Phone", Slot.PHONE),
        ("org", "Current company", Slot.CURRENT_COMPANY),
        ("resume", "Resume/CV✱", Slot.RESUME),
        ("urls[LinkedIn]", "LinkedIn URL", Slot.LINKEDIN_URL),
        ("urls[GitHub]", "GitHub URL", Slot.GITHUB_URL),
        ("urls[Portfolio]", "Portfolio URL", Slot.PORTFOLIO_URL),
    ],
)
def test_lever_standard_fields_are_recognized(name, label, expected):
    assert recognize(label, provider=AtsProvider.LEVER, name=name) is expected


def test_lever_additional_information_is_left_to_a_human():
    """Nothing in the profile answers "anything else?", so it is surfaced
    rather than filled with something adjacent."""
    assert (
        recognize("Additional information", provider=AtsProvider.LEVER, name="comments")
        is None
    )


def test_lever_custom_card_questions_are_not_recognized():
    assert (
        recognize(
            "What excites you about this role?",
            provider=AtsProvider.LEVER,
            name="cards[8f2a][field0]",
        )
        is None
    )


# ---- Ashby -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("element_id", "label", "expected"),
    [
        ("_systemfield_name", "Name", Slot.FULL_NAME),
        ("_systemfield_email", "Email", Slot.EMAIL),
        ("_systemfield_phone", "Phone", Slot.PHONE),
        ("_systemfield_resume", "Resume", Slot.RESUME),
        ("_systemfield_location", "Location", Slot.LOCATION),
    ],
)
def test_ashby_system_fields_are_recognized_by_id(element_id, label, expected):
    """Ashby's React form leaves `name` empty on its built-in fields and puts
    the meaningful token on the id."""
    assert (
        recognize(label, provider=AtsProvider.ASHBY, element_id=element_id) is expected
    )


def test_ashby_generated_field_ids_fall_through_to_the_label():
    """Ashby custom fields carry a UUID no table could enumerate, so label
    rules are what cover them."""
    assert (
        recognize(
            "LinkedIn",
            provider=AtsProvider.ASHBY,
            element_id="f1d2c3b4-5678-4abc-9def-000000000000",
        )
        is Slot.LINKEDIN_URL
    )


# ---- Scope: a provider's own names do not leak to other providers -----------


def test_lever_specific_control_names_are_not_read_on_greenhouse():
    """`org` means "current company" on Lever and nothing in particular
    anywhere else, which is why it is in Lever's table and not the shared
    one."""
    assert recognize("Company", provider=AtsProvider.LEVER, name="org") is (
        Slot.CURRENT_COMPANY
    )
    assert recognize("Company", provider=AtsProvider.GREENHOUSE, name="org") is None


def test_greenhouse_education_names_are_not_read_on_lever():
    assert (
        recognize("End Date", provider=AtsProvider.LEVER, name="educations[][end_date]")
        is None
    )


# ---- Ordering guards: the general rule must not swallow the specific one ----


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Email Address", Slot.EMAIL),
        ("Email address *", Slot.EMAIL),
        ("Address", Slot.STREET_ADDRESS),
        ("Street Address", Slot.STREET_ADDRESS),
        ("Address Line 1", Slot.STREET_ADDRESS),
        ("Address Line 2", Slot.ADDRESS_LINE_2),
        ("Apartment, suite, etc.", Slot.ADDRESS_LINE_2),
    ],
)
def test_email_wins_over_address_and_line_2_wins_over_line_1(label, expected):
    assert recognize(label) is expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Full name", Slot.FULL_NAME),
        ("Name", Slot.FULL_NAME),
        ("First name", Slot.FIRST_NAME),
        ("Given name", Slot.FIRST_NAME),
        ("Last name", Slot.LAST_NAME),
        ("Surname", Slot.LAST_NAME),
        ("Middle name", Slot.MIDDLE_NAME),
        ("Middle initial", Slot.MIDDLE_NAME),
        ("Preferred name", Slot.PREFERRED_NAME),
    ],
)
def test_modified_name_labels_never_fall_through_to_full_name(label, expected):
    """The load-bearing case: without its own rule, "Preferred name" matches
    the bare `name` rule and receives the candidate's legal name."""
    assert recognize(label) is expected


def test_location_wins_over_city_on_a_single_free_text_location_field():
    """Greenhouse's "Location (City)" wants "Austin, TX", not a bare city."""
    assert recognize("Location (City)") is Slot.LOCATION
    assert recognize("City") is Slot.CITY


def test_linkedin_and_github_win_over_the_generic_website_rule():
    assert recognize("LinkedIn profile website") is Slot.LINKEDIN_URL
    assert recognize("Personal website") is Slot.PORTFOLIO_URL


# ---- Matching is whole-word and exact-or-nothing ----------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Tick here to receive updates",  # "cv" inside "receive"
        "Zipline experience",  # "zip" inside "Zipline"
        "Nameplate engraving",  # "name" inside "Nameplate"
        "Discovery call availability",  # "cv" is not inside "Discovery" either
    ],
)
def test_rules_match_whole_words_not_substrings(label):
    """None of these are questions, so the interrogative guard is not what
    rejects them — whole-word matching is."""
    assert recognize(label) is None


def test_a_phrase_rule_requires_consecutive_words():
    """ "field of study" must not match a label that merely contains all
    three words scattered."""
    assert recognize("Field you studied") is None
    assert recognize("Field of study") is Slot.FIELD_OF_STUDY


def test_an_unlabelled_unnamed_field_is_not_recognized():
    assert recognize("") is None


# ---- Screening questions ----------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Do you have a GitHub account?",
        "What is your favourite programming language?",
        "Which of our values resonates most with you?",
        "Have you worked with us before?",
    ],
)
def test_interrogative_labels_are_surfaced_rather_than_matched(label):
    """A question mark means the company wrote this field. Without the
    guard, the first of these receives the candidate's GitHub URL."""
    assert recognize(label) is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        (
            "Are you legally authorized to work in the United States?",
            Slot.WORK_AUTHORIZATION,
        ),
        (
            "Will you now or in the future require sponsorship?",
            Slot.WORK_AUTHORIZATION,
        ),
        ("What is your visa status?", Slot.WORK_AUTHORIZATION),
        ("Gender", Slot.EEO_SELF_IDENTIFICATION),
        ("Race / Ethnicity", Slot.EEO_SELF_IDENTIFICATION),
        ("Are you a protected veteran?", Slot.EEO_SELF_IDENTIFICATION),
        ("Disability status", Slot.EEO_SELF_IDENTIFICATION),
    ],
)
def test_never_autofilled_slots_are_the_only_ones_a_question_may_match(label, expected):
    """These are recognized *so that* they can be refused with a useful
    reason — "answer the visa question yourself" beats "unknown field"."""
    assert recognize(label) is expected


# ---- Signal precedence ------------------------------------------------------


def test_the_control_name_outranks_the_label():
    """The portal naming a field is a statement; its label is prose. Here the
    label alone would not match at all."""
    assert recognize("Company", provider=AtsProvider.LEVER, name="org") is (
        Slot.CURRENT_COMPANY
    )


def test_autocomplete_is_read_when_the_label_is_missing():
    assert recognize("", autocomplete="given-name") is Slot.FIRST_NAME
    assert recognize("", autocomplete="family-name") is Slot.LAST_NAME
    assert recognize("", autocomplete="postal-code") is Slot.POSTAL_CODE


def test_autocomplete_outranks_the_label():
    """A portal that declared the field in a standard vocabulary is more
    trustworthy than one that only labelled it."""
    assert recognize("Town", autocomplete="address-level2") is Slot.CITY


def test_autocomplete_prefixes_are_skipped_to_reach_the_field_token():
    """Per the HTML spec the field name is the last token, after any section
    and address-purpose prefixes."""
    assert recognize("", autocomplete="shipping address-line1") is (Slot.STREET_ADDRESS)
    assert recognize("", autocomplete="section-a billing postal-code") is (
        Slot.POSTAL_CODE
    )


@pytest.mark.parametrize("autocomplete", ["off", "on", "", "nope"])
def test_uninformative_autocomplete_values_contribute_nothing(autocomplete):
    """`autocomplete="off"` says how the browser should behave, not what the
    field is — so the label still decides."""
    assert recognize("Email", autocomplete=autocomplete) is Slot.EMAIL
    assert recognize("", autocomplete=autocomplete) is None
