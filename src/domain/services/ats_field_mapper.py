"""recognize_application_field — decides which `ApplicationFieldSlot`, if
any, a field on a Greenhouse, Lever, or Ashby application form is asking
for.

Scope is the point (Greenhouse, Lever, Ashby only)
--------------------------------------------------
`provider` is a required `AtsProvider`, and that enum has exactly three
members. Workday and everything else are out of scope not by convention but
because there is no value to pass: a caller cannot ask this function about a
form it was never taught to read. This mirrors `identify_ats_board`'s
allowlist, which is what resolves an apply URL to a provider in the first
place — the two together mean an unrecognized portal is refused before any
field is ever examined, rather than mapped on a hopeful guess.

The dynamic platforms (Workday chief among them) are a different problem,
not a longer version of this one: they render the form in stages, re-mount
controls between steps, and expose almost nothing stable to key on.
Attempting them with these rules would produce confident wrong answers.

Recognition, in descending order of trust
----------------------------------------
1. **The control's own name/id.** `job_application[first_name]`,
   `urls[LinkedIn]`, `_systemfield_email` — the portal stating what the
   field is. Exact table lookup, so it either matches or contributes
   nothing.
2. **The `autocomplete` attribute.** A standardized vocabulary the portal
   opted into; more reliable than prose, just rarer.
3. **The label.** Ordered phrase rules over the label's word tokens. This
   carries most of the real coverage, especially on Ashby, where inputs
   carry generated names.

Every step is exact-or-nothing at its own level of precision: table lookups
are exact, and label rules match whole words in sequence, never substrings.
There is no scoring, no edit distance, and no nearest-slot fallback,
because the cost of the two outcomes is wildly asymmetric. An unrecognized
field costs a human a moment's attention (see the "not guessed" contract in
`AtsFormFieldPlanner`). A *misrecognized* field silently writes the wrong
answer into a real application under the candidate's name, and the only
person who ever sees it is a recruiter at the company.

Why questions are refused
-------------------------
A label containing "?" is treated as a screening question, and only
sensitive slots (`SENSITIVE_SLOTS`) may match one. Standard fields are
labelled as nouns ("Email", "Resume/CV"); a question mark is the reliable
signal that a company wrote this field itself. Without the guard, "Do you
have a GitHub account?" (a yes/no) matches the GitHub rule and receives a
URL, and "Which of our values resonates with you?" matches nothing sensible
but would keep matching more as the rule table grows. The cost is a handful
of false negatives on politely-phrased standard fields ("What is your
name?"), which are surfaced rather than mangled.

The sensitive slots are exempt because they are the exception that proves
the rule: work authorization, sponsorship, and EEO are the questions every
portal asks *as questions* ("Are you legally authorized to work in the
United States?"). They are standard fields wearing a question mark, so they
must be recognized through it — and what may then be done with them is the
sensitive-field policy's decision, not the recognizer's.
"""

from __future__ import annotations

import re

from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    is_sensitive_slot,
)
from src.domain.value_objects.ats_form_question import AtsFormQuestion
from src.domain.value_objects.ats_provider import AtsProvider

#: Splits a label into word tokens. Everything that is not alphanumeric is a
#: separator, which is what makes "Resume/CV", "Email address*", and
#: "Full name ✱" tokenize the way a reader would read them.
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")

#: Splits a control name on bracket syntax, so `job_application[educations]
#: [][school_name_id]` becomes its meaningful segments.
_BRACKET_RE = re.compile(r"[\[\]]+")

#: Ashby prefixes its built-in fields with this on the `name`/`id`; stripping
#: it reduces `_systemfield_email` to a key the shared table already knows.
_ASHBY_SYSTEM_FIELD_PREFIX = "_systemfield_"


# ---- Control-name tables -----------------------------------------------------

#: Control names that mean the same thing on all three platforms. Kept
#: separate from the per-provider tables so a key only lands here once it is
#: safe everywhere — a name that means one thing on Lever and another on
#: Greenhouse must never be in this table.
_SHARED_CONTROL_NAMES: dict[str, ApplicationFieldSlot] = {
    "name": ApplicationFieldSlot.FULL_NAME,
    "fullname": ApplicationFieldSlot.FULL_NAME,
    "full_name": ApplicationFieldSlot.FULL_NAME,
    "firstname": ApplicationFieldSlot.FIRST_NAME,
    "first_name": ApplicationFieldSlot.FIRST_NAME,
    "lastname": ApplicationFieldSlot.LAST_NAME,
    "last_name": ApplicationFieldSlot.LAST_NAME,
    "middlename": ApplicationFieldSlot.MIDDLE_NAME,
    "middle_name": ApplicationFieldSlot.MIDDLE_NAME,
    "preferred_name": ApplicationFieldSlot.PREFERRED_NAME,
    "email": ApplicationFieldSlot.EMAIL,
    "email_address": ApplicationFieldSlot.EMAIL,
    "phone": ApplicationFieldSlot.PHONE,
    "phone_number": ApplicationFieldSlot.PHONE,
    "location": ApplicationFieldSlot.LOCATION,
    "city": ApplicationFieldSlot.CITY,
    "state": ApplicationFieldSlot.STATE_OR_REGION,
    "region": ApplicationFieldSlot.STATE_OR_REGION,
    "postal_code": ApplicationFieldSlot.POSTAL_CODE,
    "zip": ApplicationFieldSlot.POSTAL_CODE,
    "country": ApplicationFieldSlot.COUNTRY,
    "linkedin": ApplicationFieldSlot.LINKEDIN_URL,
    "linkedin_url": ApplicationFieldSlot.LINKEDIN_URL,
    "github": ApplicationFieldSlot.GITHUB_URL,
    "github_url": ApplicationFieldSlot.GITHUB_URL,
    "portfolio": ApplicationFieldSlot.PORTFOLIO_URL,
    "website": ApplicationFieldSlot.PORTFOLIO_URL,
    "resume": ApplicationFieldSlot.RESUME,
    "resume_text": ApplicationFieldSlot.RESUME,
    "coverletter": ApplicationFieldSlot.COVER_LETTER,
    "cover_letter": ApplicationFieldSlot.COVER_LETTER,
    "cover_letter_text": ApplicationFieldSlot.COVER_LETTER,
}

#: Per-provider control names, consulted before the shared table so a
#: platform-specific meaning always wins. Ashby has no entries: its built-in
#: fields all reduce to shared keys once `_systemfield_` is stripped, and its
#: custom fields carry generated ids that no table could enumerate — Ashby
#: coverage therefore rests on the label rules by design.
_PROVIDER_CONTROL_NAMES: dict[AtsProvider, dict[str, ApplicationFieldSlot]] = {
    AtsProvider.GREENHOUSE: {
        # Greenhouse's education block repeats, so its date fields are only
        # unambiguous when read together with their parent segment: a bare
        # `start_date` could just as easily belong to an employment block.
        "educations.school_name_id": ApplicationFieldSlot.SCHOOL,
        "educations.degree_id": ApplicationFieldSlot.DEGREE,
        "educations.discipline_id": ApplicationFieldSlot.FIELD_OF_STUDY,
        "educations.start_date": ApplicationFieldSlot.EDUCATION_START_DATE,
        "educations.end_date": ApplicationFieldSlot.EDUCATION_END_DATE,
    },
    AtsProvider.LEVER: {
        # Lever's "Current company" field is named `org`, which means
        # nothing anywhere else and so is not in the shared table.
        "org": ApplicationFieldSlot.CURRENT_COMPANY,
        "urls.linkedin": ApplicationFieldSlot.LINKEDIN_URL,
        "urls.github": ApplicationFieldSlot.GITHUB_URL,
        "urls.portfolio": ApplicationFieldSlot.PORTFOLIO_URL,
    },
}


# ---- The `autocomplete` vocabulary -------------------------------------------

#: WHATWG autofill field names → slots. Only tokens whose meaning is
#: unambiguous for a job application are listed: `url`, for instance, is
#: absent because it says a field takes a URL, not *which* URL.
_AUTOCOMPLETE_SLOTS: dict[str, ApplicationFieldSlot] = {
    "name": ApplicationFieldSlot.FULL_NAME,
    "given-name": ApplicationFieldSlot.FIRST_NAME,
    "additional-name": ApplicationFieldSlot.MIDDLE_NAME,
    "family-name": ApplicationFieldSlot.LAST_NAME,
    "nickname": ApplicationFieldSlot.PREFERRED_NAME,
    "email": ApplicationFieldSlot.EMAIL,
    "tel": ApplicationFieldSlot.PHONE,
    "tel-national": ApplicationFieldSlot.PHONE,
    "street-address": ApplicationFieldSlot.STREET_ADDRESS,
    "address-line1": ApplicationFieldSlot.STREET_ADDRESS,
    "address-line2": ApplicationFieldSlot.ADDRESS_LINE_2,
    "address-level2": ApplicationFieldSlot.CITY,
    "address-level1": ApplicationFieldSlot.STATE_OR_REGION,
    "postal-code": ApplicationFieldSlot.POSTAL_CODE,
    "country": ApplicationFieldSlot.COUNTRY,
    "country-name": ApplicationFieldSlot.COUNTRY,
    "organization": ApplicationFieldSlot.CURRENT_COMPANY,
    "organization-title": ApplicationFieldSlot.CURRENT_TITLE,
}


# ---- Label rules -------------------------------------------------------------

#: Ordered `(phrase, slot)` rules matched against the label's word tokens;
#: the first match wins, so **order encodes specificity** and moving an
#: entry changes behavior.
#:
#: Four ordering constraints are load-bearing and must survive any edit:
#:
#: - the sensitive block precedes everything, so "Country of citizenship"
#:   cannot be claimed by the generic `country` rule and answered with the
#:   candidate's mailing-address country.
#: - `email` precedes the address rules, or "Email address" becomes a
#:   street address.
#: - `address line 2` precedes bare `address`, and the modified name rules
#:   (`middle`/`preferred`) precede bare `name`, or the general rule
#:   swallows the specific field and answers a question it was not asked.
#: - `location` precedes `city`, so Greenhouse's single "Location (City)"
#:   field gets the candidate's whole location string rather than a bare
#:   city into a field that wants "Austin, TX".
_LABEL_RULES: tuple[tuple[tuple[str, ...], ApplicationFieldSlot], ...] = (
    # ---- Sensitive fields, first ----------------------------------------
    # Ahead of everything else for two reasons: these are the highest-stakes
    # questions on the form, and several of their labels contain words the
    # general rules would otherwise claim ("Country of citizenship" →
    # `country`, "Visa status" → nothing, but "Citizenship status" would
    # drift). Each maps to its own slot because each takes a different
    # answer — see `ApplicationFieldSlot`.
    #
    # Sponsorship precedes visa, so "Do you require visa sponsorship?" is
    # read as the sponsorship question rather than as a request for a visa
    # type. "Citizenship status" precedes bare "citizenship" for the same
    # reason: it asks which category the candidate is in, not which country.
    (("visa", "sponsorship"), ApplicationFieldSlot.SPONSORSHIP_REQUIRED),
    (("sponsorship",), ApplicationFieldSlot.SPONSORSHIP_REQUIRED),
    (("sponsor",), ApplicationFieldSlot.SPONSORSHIP_REQUIRED),
    (("citizenship", "status"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("country", "of", "citizenship"), ApplicationFieldSlot.CITIZENSHIP_COUNTRY),
    (("citizenship",), ApplicationFieldSlot.CITIZENSHIP_COUNTRY),
    (("work", "authorization"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("work", "authorisation"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("authorized", "to", "work"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("authorised", "to", "work"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("legally", "authorized"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("legally", "authorised"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("eligible", "to", "work"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("right", "to", "work"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("work", "permit"), ApplicationFieldSlot.WORK_AUTHORIZATION),
    (("visa", "type"), ApplicationFieldSlot.VISA_TYPE),
    (("visa", "status"), ApplicationFieldSlot.VISA_TYPE),
    (("visa",), ApplicationFieldSlot.VISA_TYPE),
    # EEO self-identification. Recognized precisely so it can be refused
    # with a useful reason — never to be answered.
    (("gender",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("race",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("ethnicity",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("hispanic",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("latino",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("veteran",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("disability",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("disabled",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    (("pronouns",), ApplicationFieldSlot.EEO_SELF_IDENTIFICATION),
    # Documents. Next because these labels are the most distinctive on the
    # form and the most costly to miss.
    (("cover", "letter"), ApplicationFieldSlot.COVER_LETTER),
    (("resume",), ApplicationFieldSlot.RESUME),
    (("cv",), ApplicationFieldSlot.RESUME),
    (("curriculum", "vitae"), ApplicationFieldSlot.RESUME),
    # Names — every modified form before the bare one.
    (("first", "name"), ApplicationFieldSlot.FIRST_NAME),
    (("given", "name"), ApplicationFieldSlot.FIRST_NAME),
    (("last", "name"), ApplicationFieldSlot.LAST_NAME),
    (("family", "name"), ApplicationFieldSlot.LAST_NAME),
    (("surname",), ApplicationFieldSlot.LAST_NAME),
    (("middle", "name"), ApplicationFieldSlot.MIDDLE_NAME),
    (("middle", "initial"), ApplicationFieldSlot.MIDDLE_NAME),
    (("preferred", "name"), ApplicationFieldSlot.PREFERRED_NAME),
    (("nickname",), ApplicationFieldSlot.PREFERRED_NAME),
    (("full", "name"), ApplicationFieldSlot.FULL_NAME),
    (("name",), ApplicationFieldSlot.FULL_NAME),
    # Contact. `email` must stay ahead of the address rules.
    (("email",), ApplicationFieldSlot.EMAIL),
    (("e", "mail"), ApplicationFieldSlot.EMAIL),
    (("phone",), ApplicationFieldSlot.PHONE),
    (("telephone",), ApplicationFieldSlot.PHONE),
    (("mobile",), ApplicationFieldSlot.PHONE),
    (("cell",), ApplicationFieldSlot.PHONE),
    # Links, before the generic "website" rule they would otherwise lose to.
    (("linkedin",), ApplicationFieldSlot.LINKEDIN_URL),
    (("github",), ApplicationFieldSlot.GITHUB_URL),
    (("portfolio",), ApplicationFieldSlot.PORTFOLIO_URL),
    (("personal", "site"), ApplicationFieldSlot.PORTFOLIO_URL),
    (("website",), ApplicationFieldSlot.PORTFOLIO_URL),
    # Location before city, and the decomposed address after both.
    (("location",), ApplicationFieldSlot.LOCATION),
    (("address", "line", "2"), ApplicationFieldSlot.ADDRESS_LINE_2),
    (("apartment",), ApplicationFieldSlot.ADDRESS_LINE_2),
    (("street", "address"), ApplicationFieldSlot.STREET_ADDRESS),
    (("address", "line", "1"), ApplicationFieldSlot.STREET_ADDRESS),
    (("address",), ApplicationFieldSlot.STREET_ADDRESS),
    (("city",), ApplicationFieldSlot.CITY),
    (("town",), ApplicationFieldSlot.CITY),
    (("state",), ApplicationFieldSlot.STATE_OR_REGION),
    (("province",), ApplicationFieldSlot.STATE_OR_REGION),
    (("region",), ApplicationFieldSlot.STATE_OR_REGION),
    (("postal", "code"), ApplicationFieldSlot.POSTAL_CODE),
    (("postcode",), ApplicationFieldSlot.POSTAL_CODE),
    (("zip",), ApplicationFieldSlot.POSTAL_CODE),
    (("country",), ApplicationFieldSlot.COUNTRY),
    # Current employment. Only the qualified forms: a bare "Company" on an
    # application is at least as likely to be asking something else.
    (("current", "company"), ApplicationFieldSlot.CURRENT_COMPANY),
    (("current", "employer"), ApplicationFieldSlot.CURRENT_COMPANY),
    (("current", "title"), ApplicationFieldSlot.CURRENT_TITLE),
    (("current", "role"), ApplicationFieldSlot.CURRENT_TITLE),
    (("job", "title"), ApplicationFieldSlot.CURRENT_TITLE),
    # Education. No rules for bare "Start date"/"End date": inside an
    # education block they mean one thing and inside an employment block
    # another, and a label alone cannot tell them apart — Greenhouse's
    # control names can, which is where those two slots come from.
    (("school",), ApplicationFieldSlot.SCHOOL),
    (("university",), ApplicationFieldSlot.SCHOOL),
    (("college",), ApplicationFieldSlot.SCHOOL),
    (("institution",), ApplicationFieldSlot.SCHOOL),
    (("degree",), ApplicationFieldSlot.DEGREE),
    (("field", "of", "study"), ApplicationFieldSlot.FIELD_OF_STUDY),
    (("discipline",), ApplicationFieldSlot.FIELD_OF_STUDY),
    (("major",), ApplicationFieldSlot.FIELD_OF_STUDY),
    # Ordered after the "major" tokens above but matched on its own word, so a
    # "Minor" box is answered from the minors and never from a major.
    (("minor",), ApplicationFieldSlot.MINOR),
)


def recognize_application_field(
    question: AtsFormQuestion, *, provider: AtsProvider
) -> ApplicationFieldSlot | None:
    """Return the slot `question` is asking for, or None if it isn't one
    ApplyFlow recognizes.

    None is the safe, expected outcome for every field a company wrote
    itself, and callers are required to surface those rather than fill them
    (see `AtsFormFieldPlanner`). It is never an error.
    """
    from_name = _recognize_by_control_name(question, provider=provider)
    if from_name is not None:
        return from_name

    from_autocomplete = _recognize_by_autocomplete(question.autocomplete)
    if from_autocomplete is not None:
        return from_autocomplete

    return _recognize_by_label(question.label)


# ---- Strategy 1: the control's own name/id -----------------------------------


def _recognize_by_control_name(
    question: AtsFormQuestion, *, provider: AtsProvider
) -> ApplicationFieldSlot | None:
    """Look the field's `name`, then its `id`, up in the provider's table
    and then the shared one.

    `name` is tried before `id` because a form submits under its names,
    which makes them the portal's authoritative statement about a field;
    ids are frequently framework-generated decoration. Within each, the
    most specific key is tried first (see `_control_name_keys`).
    """
    provider_names = _PROVIDER_CONTROL_NAMES.get(provider, {})
    for raw in (question.control_name, question.element_id):
        for key in _control_name_keys(raw):
            for table in (provider_names, _SHARED_CONTROL_NAMES):
                slot = table.get(key)
                if slot is not None:
                    return slot
    return None


def _control_name_keys(raw: str) -> tuple[str, ...]:
    """Reduce a control name to lookup keys, most specific first.

    ATS forms nest their control names, and the nesting carries meaning
    that the leaf alone loses: `job_application[educations][][end_date]`
    is an education date, while a bare `end_date` could be anything. So a
    name yields up to three keys — the whole string, its last two segments
    joined (`educations.end_date`), and its leaf — and the caller tries them
    in that order.

    Ashby's `_systemfield_` prefix is stripped as an extra key rather than
    in place of one: the prefixed form stays available for a table that
    wants to match it exactly, while `_systemfield_email` also reaches the
    shared table's `email`.
    """
    lowered = raw.strip().lower()
    if not lowered:
        return ()

    segments = tuple(segment for segment in _BRACKET_RE.split(lowered) if segment)
    keys = [lowered]
    if len(segments) >= 2:
        keys.append(f"{segments[-2]}.{segments[-1]}")
    if segments:
        keys.append(segments[-1])
    if lowered.startswith(_ASHBY_SYSTEM_FIELD_PREFIX):
        keys.append(lowered.removeprefix(_ASHBY_SYSTEM_FIELD_PREFIX))

    # dict.fromkeys dedupes while keeping the specificity order above —
    # single-segment names produce the same key three times.
    return tuple(dict.fromkeys(keys))


# ---- Strategy 2: the `autocomplete` attribute --------------------------------


def _recognize_by_autocomplete(autocomplete: str) -> ApplicationFieldSlot | None:
    """Read the field name out of an `autocomplete` token list.

    Per the HTML spec the field name is the last meaningful token, after any
    optional section and address-purpose prefixes (`"shipping
    address-line1"`), so tokens are examined from the right. `"off"` and
    `"on"` are not in the table and so contribute nothing, which is the
    correct reading of both.
    """
    for token in reversed(autocomplete.strip().lower().split()):
        slot = _AUTOCOMPLETE_SLOTS.get(token)
        if slot is not None:
            return slot
    return None


# ---- Strategy 3: the label ---------------------------------------------------


def _recognize_by_label(label: str) -> ApplicationFieldSlot | None:
    """Match the label's word tokens against `_LABEL_RULES`, first hit wins.

    Interrogative labels are held to the sensitive slots only — see the
    module docstring on why a question mark is treated as "a company wrote
    this field", and why the always-asked legal and EEO questions are the
    exception.

    First-match-wins is checked against `_CONFLICTING_LEGAL_SLOTS` before it
    is trusted, because on one common phrasing the winner is the wrong
    question — see that constant.
    """
    tokens = _tokenize(label)
    if not tokens:
        return None

    if _asks_more_than_one_legal_question(tokens):
        return None

    is_question = "?" in label
    for phrase, slot in _LABEL_RULES:
        if not _contains_phrase(tokens, phrase):
            continue
        if is_question and not is_sensitive_slot(slot):
            return None
        if _asks_something_no_stored_field_states(tokens, slot):
            return None
        return slot
    return None


#: The one pair of legal-attestation slots whose phrases routinely appear in
#: the *same* label, asking a question that neither of them answers.
#:
#: "Are you legally authorized to work in the United States **without
#: sponsorship**?" is a standard Greenhouse/Lever screening question, and it
#: matches both the authorization rules and the sponsorship rules. Ordering
#: decides the winner, and the winner is sponsorship — so a US citizen, whose
#: record says "does not require sponsorship", gets **"No"** written into a
#: field whose truthful answer is **"Yes"**. The two questions have opposite
#: polarity, so picking either slot inverts the declaration for one group of
#: candidates: the compound question asks for the *conjunction* (authorized
#: AND needing no sponsor) and no single stored field states it.
#:
#: Inverting a legal declaration is the specific harm this whole module is
#: ordered to avoid (see the module docstring, and `_SENSITIVE_ANSWER_KINDS`
#: in `AtsFormFieldPlanner`, which excludes checkboxes for the same reason),
#: so a label carrying both is refused outright and surfaced for the
#: candidate to answer.
#:
#: Deliberately this pair and no other. A general "two sensitive slots
#: matched" rule would surface the canonical sponsorship question itself —
#: "Will you now or in the future require sponsorship for employment **visa
#: status**?" also matches the `visa status` rule — and refusing to answer
#: the most common sponsorship question on every portal is a worse outcome
#: than the narrow gap this closes.
#:
#: Answering the compound question exactly, rather than surfacing it, needs a
#: slot of its own with its own derivation — an Epic 01/05 change, tracked in
#: `docs/sensitive-field-enforcement-check.md`.
_CONFLICTING_LEGAL_SLOTS: frozenset[ApplicationFieldSlot] = frozenset(
    {
        ApplicationFieldSlot.WORK_AUTHORIZATION,
        ApplicationFieldSlot.SPONSORSHIP_REQUIRED,
    }
)


def _asks_more_than_one_legal_question(tokens: tuple[str, ...]) -> bool:
    """Whether this label matches rules for both conflicting legal slots."""
    matched = {
        slot
        for phrase, slot in _LABEL_RULES
        if slot in _CONFLICTING_LEGAL_SLOTS and _contains_phrase(tokens, phrase)
    }
    return len(matched) > 1


#: Legal-attestation slots whose stored value answers exactly one question:
#: "what is the candidate's position *right now*". None of them states a date,
#: and none of them states a history.
_CURRENT_STATE_LEGAL_SLOTS: frozenset[ApplicationFieldSlot] = frozenset(
    {
        ApplicationFieldSlot.WORK_AUTHORIZATION,
        ApplicationFieldSlot.SPONSORSHIP_REQUIRED,
        ApplicationFieldSlot.VISA_TYPE,
    }
)

#: Words that turn one of those labels into a question the record cannot state.
#:
#: The second half of the `_CONFLICTING_LEGAL_SLOTS` problem, and the same root
#: cause: the sensitive label rules are greedy. They match one phrase and never
#: ask whether the label is posing a *different* question from the slot's
#: canonical one. Two phrasings found by the Epic 07 hardening pass, both of
#: which resolved to a legal slot and got a confident wrong answer written into
#: a text input (a select or radio refuses the value and surfaces the field, so
#: only free-text inputs were affected):
#:
#: - **History.** "Have you ever been sponsored for a visa?" and "Are you
#:   currently on a visa sponsored by your employer?" fall past the sponsorship
#:   rules — which need the token `sponsor`/`sponsorship`, not `sponsored` — to
#:   the bare `visa` rule, and a visa holder got `"H-1B"` written into a yes/no
#:   question. Sponsorship *history* is not something this record stores at all.
#: - **Dates.** "Work permit expiry date" matches the `work permit` rule and
#:   resolves to `WORK_AUTHORIZATION`, which answers "Yes"/"No" — so `"Yes"`
#:   went into a field asking for a date. No legal slot stores a date.
#:
#: In both cases the truthful answer under exact-or-refuse is to refuse, so the
#: label is surfaced for the candidate.
#:
#: Scoped to the three current-state slots deliberately, and matched as whole
#: words, so this cannot reach the canonical phrasings the previous fix was
#: careful to preserve: "Will you now or in the future require sponsorship for
#: employment visa status?" carries none of these tokens, and neither does "Do
#: you require visa sponsorship?" or "Are you legally authorized to work in the
#: US?". `date` is included even though it is a common word, because no legal
#: slot answers a date under any phrasing — and the cost of over-refusing is a
#: question the candidate answers themselves, against a wrong legal declaration
#: on a real application.
_UNANSWERABLE_LEGAL_QUALIFIERS: frozenset[str] = frozenset(
    {
        # Asks when something lapses.
        "expiry",
        "expiration",
        "expires",
        "expire",
        "expiring",
        "date",
        # "Visa valid until". `valid` alone is deliberately absent: "Is your
        # work authorization valid?" is a legitimate current-state question and
        # the record does answer it.
        "until",
        # Asks about the past rather than the present.
        "sponsored",
        "ever",
        "previously",
    }
)


def _asks_something_no_stored_field_states(
    tokens: tuple[str, ...], slot: ApplicationFieldSlot
) -> bool:
    """Whether a matched legal label is asking for a date or a history.

    Both are questions the profile has no field for, so the slot's canonical
    answer would be a confident wrong value in a legal field. See
    `_UNANSWERABLE_LEGAL_QUALIFIERS`.
    """
    if slot not in _CURRENT_STATE_LEGAL_SLOTS:
        return False
    return any(token in _UNANSWERABLE_LEGAL_QUALIFIERS for token in tokens)


def _tokenize(label: str) -> tuple[str, ...]:
    """Lowercase a label and split it into word tokens.

    Punctuation, required-field markers, and separators all become
    boundaries, so "Resume/CV ✱" reads as ("resume", "cv") — the same two
    words a person sees.
    """
    return tuple(token for token in _NON_WORD_RE.split(label.lower()) if token)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """Whether `phrase` appears in `tokens` as consecutive whole words.

    Whole words, never substrings: "cv" must not match inside "receive",
    and "zip" must not match inside "zipline". Consecutive, so "field of
    study" does not match a label that merely mentions all three words.
    """
    span = len(phrase)
    return any(
        tokens[start : start + span] == phrase
        for start in range(len(tokens) - span + 1)
    )
