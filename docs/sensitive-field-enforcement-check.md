# Sensitive-field enforcement check — verification report

Epics 01 and 05 each implement half of ApplyFlow's sensitive-field handling:
Epic 01 stores the two records (`WorkAuthorization`, `EeoSelfIdentification`),
Epic 05 decides what may be done with them. Both are unit-tested in place.
This check asked a different question — do the two rules actually hold *end to
end*, across the seams between profile, tailoring, and autofill — and it is
where a rule every layer implements correctly can still fail as a whole.

The two rules, restated:

1. **Work authorization and sponsorship are always exactly accurate.** Exact
   or refused; never approximate. Declining to answer is not the safe default
   here, because an unanswered required question stalls the application.
2. **EEO self-identification is never auto-filled.** Refused unconditionally
   and surfaced for a per-application decision by the candidate.

**Verdict: both rules hold, after one fix.** Verification found three defects
in rule 1 and none in rule 2. The most serious — an *inverted* legal
declaration — is fixed here. The other two are documented below and routed.

## The check

`tests/acceptance/test_sensitive_field_enforcement.py` — 111 cases, and unlike
the epic pipelines in that directory it is **not gated behind an env var**. It
drives no browser and no database, but reaches the same production code they
do: the real persistence mappers, the real recognizer, the real policy, the
real planner, the real autofill use case, with only the browser faked. A rule
this consequential should not be verified only on the runs somebody remembered
to opt into.

```bash
pytest tests/acceptance/test_sensitive_field_enforcement.py -v
```

Three things about how it is built are load-bearing:

- **Profiles are round-tripped through storage.** Every profile goes through
  `SqlAlchemyProfileRepository`'s own mapping functions before autofill sees
  it, so the policy reads what storage would return rather than what the test
  constructed. Those columns are encrypted at rest (Epic 07), and the mapping
  is exactly where a `requires_sponsorship=False` could quietly become `None`
  — which silently downgrades an exact "No" into a refusal. No database is
  needed to exercise that; the mapping is the part that can be wrong.
- **Assertions are against the bytes written to the page**, via
  `session.filled`, not against the report. The report is a *claim* about what
  happened.
- **The work-authorization truth table is written out once**, all thirteen
  stored shapes with their required answers, so changing the derivation means
  coming to that table and stating a case.

### It was verified to have teeth

A green suite that would stay green with the feature broken proves nothing, so
four mutations were introduced and reverted:

| Mutation | Caught by |
| --- | --- |
| Revert the compound-question guard | 6 failures, incl. the regression test |
| Let the policy answer EEO from the profile | 10 failures across 5 tests |
| Add EEO to the tailoring fact corpus | tailoring test + static guard |
| Drop a `False` sponsorship answer in storage mapping | 3 failures |

## What was verified

### AC1 — work authorization through the full profile → autofill path

All thirteen combinations of `WorkAuthorizationStatus` × `requires_sponsorship`
were driven from a stored profile through to the value written to the form.
Also confirmed: free-text details (citizenship country, visa type) arrive
verbatim including non-ASCII; an unattested (resume-parsed) record is still
refused after the storage round-trip; nothing between the domain policy and
the browser harness rewrites the answer; and every filled legal value carries
`requires_confirmation`.

### AC2 — EEO self-ID is never auto-filled

Confirmed at four independent levels:

- **Recognizer sweep** — 24 EEO wordings × 3 providers (72 cases). Every one
  resolves either to the EEO slot or to nothing. Neither is answerable, and
  the third outcome — an answerable slot — never occurs. This is the cheapest
  place to catch the regression where, say, a new rule claims "National
  origin" for `country` and writes the candidate's mailing-address country
  into a demographic question.
- **Whole autofill pass** on all three portals with every EEO category on
  file: nothing written, each field surfaced as `requires_candidate_answer`,
  `requires_confirmation` correctly false.
- **Blunt value sweep** — no stored category string appears anywhere in what
  was written, whatever the field was labelled or resolved to.
- **Static guard** (`test_the_eeo_record_is_unreachable_from_every_form_filling_module`)
  — an AST scan proving no module outside the profile entity, the value
  object, and the persistence mapping reads the EEO record *at all*. The
  behavioural tests prove today's paths refuse it; this one is about the path
  somebody adds next. A prompt builder, a new resolver, a "prefill from last
  application" convenience — each a reasonable-looking diff, each defeating
  the rule. Parsed rather than grepped, so the many docstrings discussing EEO
  by name are not mistaken for code that touches it. Same spirit as
  `tests/infrastructure/test_pii_log_call_sites.py`.

Also confirmed: the refusal does not vary with what is on file — including
when every category is `DECLINE_TO_SELF_IDENTIFY`. A stored decline is still a
disclosure decision made for *another* employer, and carrying it forward would
convert a per-application choice into a standing one just as surely as
carrying an answer forward would.

And the other side of the rule, which matters just as much: refusing to
autofill EEO is only defensible if the candidate can still disclose.
`AnswerApplicationField` remains the one path that exists, and what it
produces is marked `answered_by_candidate` with `requires_confirmation`
cleared — so a disclosure they typed can never later read as one ApplyFlow
filled in for them.

### AC3 — across profile, tailoring, and autofill

**Tailoring was the gap in existing coverage.** No test asserted anything
about EEO in the generation path, and it is the layer with no field-level
policy to protect it: facts become an LLM prompt, and anything in that prompt
can land in a resume or cover letter body, where no review gate is watching
for demographic data. Verified that neither `CandidateFactExtractor.extract`
nor `extract_provenance_backed` yields anything from the EEO record even when
every category is answered, and that work authorization — the opposite case —
does appear, exactly once, carrying the provenance the guard validates against.

## Findings

### F1 — inverted legal declaration on a compound question — FIXED

**Severity: high.** `"Are you legally authorized to work in the United States
**without sponsorship**?"` — a standard Greenhouse/Lever screening question —
matches both the authorization rules and the sponsorship rules in
`_LABEL_RULES`. Ordering resolved it to the sponsorship slot, so:

| Candidate | Truthful answer | What ApplyFlow wrote |
| --- | --- | --- |
| US citizen | Yes | **No** |
| Requires sponsorship | No | **Yes** |

Inverted for every candidate, in both directions. This is precisely the harm
`ats_field_mapper`'s ordering rules and `AtsFormFieldPlanner`'s exclusion of
checkboxes both exist to prevent, arriving through a path neither covered.

The question asks for a *conjunction* — authorized AND needing no sponsor —
and no single stored field states it, so under exact-or-refuse the answer is
to refuse. `_CONFLICTING_LEGAL_SLOTS` in `src/domain/services/ats_field_mapper.py`
now surfaces a label matching both slots for the candidate to answer.

The guard is deliberately that one pair and no other. A general "two sensitive
slots matched" rule would also surface *the canonical sponsorship question* —
"…require sponsorship for employment **visa status**?" matches the visa rules
too — and refusing the most common sponsorship phrasing on every portal is a
worse outcome than the narrow gap this closes. A test pins that specifically.

**Routed:** answering the compound question *exactly* rather than surfacing it
needs a slot of its own (`WORK_AUTHORIZATION_WITHOUT_SPONSORSHIP`) deriving
from authorized-AND-not-requiring-sponsorship, refusing where either is
unknown. Enum, mapper rules, policy, planner, tests — an Epic 01/05 change,
out of scope for a verification pass.

### F2 — sponsorship-history questions answered with a visa type — ROUTED

**Severity: medium.** `"Have you ever been sponsored for a visa?"` and `"Are
you currently on a visa sponsored by your employer?"` fall through the
sponsorship rules (which need the token `sponsor`/`sponsorship`, not
`sponsored`) to the bare `visa` rule, and resolve to `VISA_TYPE`. A visa
holder therefore gets `"H-1B"` written into a yes/no question.

Contained but not correct: on a select or radio the portal refuses the value
and the field is surfaced (`NOT_ACCEPTED`), so the common case is safe. On a
**text** input it is written. Not an inversion, but a wrong value in a legal
field — and the underlying question (sponsorship *history*) is one the record
does not store at all, so the right outcome is to surface it.

### F3 — "Work permit expiry date" answered "Yes" — ROUTED

**Severity: low.** The `work permit` rule claims the label and resolves to
`WORK_AUTHORIZATION`, which answers "Yes"/"No". On a `DATE` widget the planner
surfaces it (`unsupported_field_kind`); on a **text** input, `"Yes"` is
written into a field asking for a date. The record stores no expiry date, so
this should surface.

F2 and F3 share a root cause with F1: **the sensitive-block label rules are
greedy** — they match one phrase and never ask whether the label is posing a
different question than the slot's canonical one. Fixing them properly means
tightening those rules with their own test matrix, which is Epic 01/05
rule-tuning rather than verification work.

## Confirmed non-issues

Checked and found correct; recorded so they are not re-investigated:

- **Answer memory cannot replay an EEO disclosure.** `AnswerApplicationField`
  does not write to `AnswerMemory`, so an EEO answer given for one application
  cannot be recalled by `RelevantAnswerSelector` or `FindSimilarAnswer` for the
  next. This was the most plausible route to the exact harm the rule exists to
  prevent.
- **Neither the HTTP API nor the frontend re-displays stored EEO data.** There
  is no profile endpoint exposing it, and `ReviewAndSubmit.tsx` /
  `AutofillReview.tsx` read `sensitivity` from the backend rather than
  inferring it.
- **The submit gate holds.** Every sensitive field starts `PENDING` and
  `record_submission` refuses while any is unsettled, so nothing sensitive is
  submitted unlooked-at.
- **`requires_sponsorship=False` survives the encrypted-boolean mapping** as
  `False`, not `None`.

## Known limitation, unchanged

**Jurisdiction.** `WorkAuthorization` does not record which country its status
refers to, so "Are you eligible to work in **Canada**?" is answered from a
record that may describe US authorization. Pre-existing, documented in
`decide_sensitive_field`'s docstring, and out of scope here — the fix is an
Epic 01 data-model change. The standing safeguard is that every filled legal
answer is flagged `requires_confirmation`, so the candidate sees it before
anything is submitted.

Note that F1's fix interacts with this benignly: `"Are you eligible to work in
the UK without sponsorship?"` is now surfaced rather than answered from a
jurisdiction-less record, which is the better outcome on both counts.

## Covered elsewhere, not repeated here

- The policy's own decision table — `tests/domain/test_sensitive_field_policy.py`
- Per-platform mapping rules and every surface reason —
  `tests/domain/test_ats_field_mapper.py`,
  `tests/application/test_autofill_application_form.py`
- The review gates and blockers — `tests/domain/test_application_review.py`,
  `tests/application/test_submit_application_form.py`
- The same flow against a real browser and a real Postgres —
  `tests/acceptance/test_epic05_autofill_pipeline.py` (opt-in)
