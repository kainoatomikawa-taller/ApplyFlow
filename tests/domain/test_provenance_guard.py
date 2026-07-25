"""Tests for ProvenanceGuard — the gate that keeps generated output inside
what the candidate's provenance-backed facts actually support.

Organized around the fabrications it has to catch (invented employers,
inflated numbers, unearned credentials, requirements claimed as
experience), the legitimate prose it must not destroy (framing, section
headings, naming the role applied for), and the reporting that makes a
strip debuggable.
"""

from __future__ import annotations

from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact
from src.domain.value_objects.provenance_source import ProvenanceSource

_RESUME = ProvenanceSource.PARSED_RESUME
_ENTERED = ProvenanceSource.USER_ENTERED
_ANSWER = ProvenanceSource.ANSWER


def _fact(text: str, source: ProvenanceSource = _RESUME) -> ProvenanceBackedFact:
    return ProvenanceBackedFact(text=text, source=source)


_FACTS = (
    _fact("Name: Dana Reyes", _ENTERED),
    _fact("Worked as Backend Engineer at Acme Corp (2019-03-01 to 2022-06-30)"),
    _fact("Backend Engineer at Acme Corp: Built payment services in Python."),
    _fact("Skill: Python"),
    _fact("Skill: Kubernetes (4 years)"),
    _fact("Studied Bachelor of Science in Computer Science at State University"),
    _fact(
        "Asked 'Have you led a team?', answered: I led a team of 5 engineers.", _ANSWER
    ),
)

_CONTEXT = ("Senior Platform Engineer", "Globex", "Austin, TX")


def _enforce(content: str, facts=_FACTS, context=_CONTEXT):
    return ProvenanceGuard().enforce(content, facts=facts, context_terms=context)


# ---- fabrications that must not survive -------------------------------------


def test_invented_employer_is_stripped():
    result = _enforce("Worked as a Staff Engineer at Initech.")

    assert result.content == ""
    assert result.violations[0].line == "Worked as a Staff Engineer at Initech."
    assert "initech" in result.violations[0].unsupported_terms


def test_inflated_headcount_is_stripped_while_the_real_one_survives():
    result = _enforce("I led a team of 5 engineers.\nI led a team of 50 engineers.")

    assert result.content == "I led a team of 5 engineers."
    assert result.violations[0].unsupported_terms == ("50",)


def test_invented_credential_is_stripped():
    result = _enforce("Earned a Master of Science at State University.")

    assert result.content == ""
    assert "master" in result.violations[0].unsupported_terms


def test_a_skill_the_candidate_never_claimed_is_stripped():
    result = _enforce("Skills: Python, Kubernetes, Rust")

    assert result.content == ""
    assert result.violations[0].unsupported_terms == ("rust",)


def test_a_job_requirement_never_backs_a_claim_about_the_candidate():
    """The posting wanting Terraform is not evidence the candidate has
    used it — the guard is given the posting's identity, never its
    requirements, precisely so this cannot invert."""
    result = _enforce(
        "I have production Terraform experience.",
        context=("Senior Platform Engineer", "Globex", "Austin, TX"),
    )

    assert result.content == ""
    assert "terraform" in result.violations[0].unsupported_terms


def test_nothing_asserting_survives_an_empty_fact_corpus():
    result = _enforce("Worked as Backend Engineer at Acme Corp.", facts=(), context=())

    assert result.content == ""
    assert result.violations


def test_a_line_mixing_a_supported_and_an_unsupported_claim_is_dropped_whole():
    result = _enforce("Built payment services in Python and Scala.")

    assert result.content == ""
    assert result.violations[0].unsupported_terms == ("scala",)


# ---- legitimate content that must survive -----------------------------------


def test_a_fully_backed_line_is_kept_byte_for_byte():
    line = "Backend Engineer at Acme Corp (2019-2022)"
    result = _enforce(line)

    assert result.content == line
    assert result.is_clean


def test_facts_across_sources_each_contribute_their_provenance():
    result = _enforce("Dana Reyes\nBuilt payment services in Python.")

    assert result.backing_sources == (_RESUME, _ENTERED)


def test_an_answer_backed_claim_traces_to_the_answer_source():
    result = _enforce("I led a team of 5 engineers.")

    assert _ANSWER in result.lines[0].backing_sources


def test_naming_the_role_and_company_applied_to_is_allowed():
    line = "I am excited to apply for the Senior Platform Engineer role at Globex."
    result = _enforce(line)

    assert result.content == line


def test_framing_and_headings_are_kept_but_claim_nothing():
    content = "Dear Hiring Manager,\n\nEXPERIENCE\n\nSincerely,"
    result = _enforce(content)

    assert result.content == content
    assert all(line.backing_sources == () for line in result.lines)


def test_blank_lines_are_preserved_so_layout_survives():
    result = _enforce("EXPERIENCE\n\nSkill: Python")

    assert result.content == "EXPERIENCE\n\nSkill: Python"


def test_statements_of_interest_need_no_provenance():
    line = "I am eager to discuss this opportunity and hope to hear from you."
    result = _enforce(line)

    assert result.content == line


def test_regular_inflections_match_the_facts_own_wording():
    """A fact's "Engineer" backs "engineering", and its "services" backs
    "service" — otherwise the guard would strip every naturally-written
    sentence."""
    result = _enforce("Engineering payment service work at Acme Corp in Python.")

    assert result.is_clean


def test_an_irregular_verb_form_is_stripped_rather_than_guessed_at():
    """The stemmer is deliberately simple, so "building" never reaches the
    facts' irregular "Built" and the line goes. Erring toward stripping is
    the safe direction: the looser the matching, the sooner a fabricated
    "Acmeworks" passes for a real "Acme"."""
    result = _enforce("Building payment services in Python.")

    assert result.violations[0].unsupported_terms == ("building",)


def test_a_sentence_final_period_does_not_break_a_match():
    result = _enforce("I worked at Acme Corp.")

    assert result.is_clean


def test_a_possessive_does_not_break_a_match():
    result = _enforce("Acme Corp's payment services were built in Python.")

    assert result.is_clean


def test_a_date_part_is_backed_by_the_full_date_in_the_facts():
    result = _enforce("Backend Engineer at Acme Corp, 2019 to 2022.")

    assert result.is_clean


def test_short_acronyms_are_not_mangled_into_each_other():
    result = ProvenanceGuard().enforce(
        "Skill: AWS\nSkill: CSS",
        facts=(_fact("Skill: AWS"),),
        context_terms=(),
    )

    assert result.content == "Skill: AWS"
    assert result.violations[0].unsupported_terms == ("css",)


# ---- reporting --------------------------------------------------------------


def test_a_violation_names_every_unsupported_term_in_order_without_repeats():
    result = _enforce("Scaled Redis and Redis clusters to 90 nodes.")

    assert result.violations[0].unsupported_terms == (
        "scaled",
        "redis",
        "clusters",
        "90",
        "nodes",
    )


def test_the_report_distinguishes_a_clean_run_from_a_stripped_one():
    clean = _enforce("Skill: Python")
    stripped = _enforce("Skill: Haskell")

    assert clean.is_clean and not clean.violations
    assert not stripped.is_clean and len(stripped.violations) == 1


def test_surviving_lines_and_violations_together_account_for_every_line():
    content = "Skill: Python\nSkill: Haskell\nSkill: Kubernetes"
    result = _enforce(content)

    assert len(result.lines) + len(result.violations) == len(content.splitlines())


def test_backing_sources_are_reported_in_provenance_declaration_order():
    result = _enforce(
        "Skill: Python\nI led a team of 5 engineers.\nDana Reyes",
    )

    assert result.backing_sources == (_RESUME, _ENTERED, _ANSWER)


def test_guarding_empty_content_yields_empty_content_and_no_violations():
    result = _enforce("")

    assert result.content == ""
    assert result.is_clean
