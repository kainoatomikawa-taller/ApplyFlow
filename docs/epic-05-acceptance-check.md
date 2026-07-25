# Epic 05 acceptance check — autofill, review, hand-off, submit

Epic 05 built the part of ApplyFlow that touches a real employer's
application form: the browser harness, the Greenhouse/Lever/Ashby field
mapping, the sensitive-field policy, the hand-off at every check only a human
can pass, and the attended submission. This document is the Definition of
Done for that epic, and the flow
`tests/acceptance/test_epic05_autofill_pipeline.py` proves it end to end
against a real browser, a real portal, and a real submission.

## What "done" means

1. On a supported ATS, the app fills the application and surfaces it for
   review.
2. Every hard boundary — CAPTCHA, signature, login — triggers a correct
   hand-off.
3. Sensitive fields are handled per policy, and EEO is never silently filled.
4. The user submits, and nothing is submitted unattended.

## Running it

The check is opt-in — it drives a real headless Chromium and writes to a real
Postgres database:

```bash
RUN_EPIC05_ACCEPTANCE_TEST=1 \
  pytest tests/acceptance/test_epic05_autofill_pipeline.py -v -s
```

Requires, via `.env` or exported env vars:

- `DATABASE_URL` — a reachable Postgres (`docker compose up db` locally, or a
  Supabase project)
- `SUPABASE_JWT_SECRET` — used both to mint the test's bearer token and by the
  app to verify it, so the run proves the real auth path
- the Chromium build Playwright expects (`playwright install chromium`, part
  of `make install`)

No API keys and no money: this epic reads and fills forms rather than
generating anything. The resume and cover letter it attaches are seeded
`ApplicationDocument` snapshots — the artifact Epic 04's check produces.

Without `RUN_EPIC05_ACCEPTANCE_TEST=1`, the test is skipped and the ordinary
`pytest` run never launches a browser or touches a database.

## Why the portal is local, and why it is still a supported ATS

The one thing this check must never do is submit an application to a real
employer. So the four forms it works against are served by a local HTTP
server on 127.0.0.1 — and Chromium is launched with

```
--host-resolver-rules=MAP boards.greenhouse.io 127.0.0.1:<port>
```

so the browser genuinely navigates `http://boards.greenhouse.io/globex/jobs/…`,
`identify_ats_board` genuinely resolves it to Greenhouse, and the Greenhouse
mapping rules are genuinely the ones under test. **Only the DNS answer is
substituted.** Everything else in the path is production code: the real
Playwright harness, the real field discovery, the real planner, the real HTTP
app with real Supabase-JWT auth, the real repositories.

The forms are Greenhouse-shaped where it counts — the control names
(`job_application[first_name]`, `job_application[resume]`,
`job_application[urls][LinkedIn]`) are what the mapping rules key on — and
they ask what real forms ask: work authorization, sponsorship, EEO
self-identification, and a screening question the company wrote itself.

**The local portal records what is posted to it.** That is the point of it
being a real server rather than a page: every claim about what ApplyFlow put
on the form is asserted twice — once against the API's report, and once
against the bytes the portal received. A report can be wrong; a POST body is
what was sent. It is also how "nothing is submitted unattended" is checked,
since for three of the four forms the recorded submissions must stay empty.

## The four forms

| Form | What it is | Expected outcome |
| --- | --- | --- |
| `/globex/jobs/4001` | a complete application form | filled, reviewed, submitted by the candidate |
| `/globex/jobs/4002` | a sign-in wall with a password box | **nothing filled**, login hand-off |
| `/globex/jobs/4003` | an ordinary form with a reCAPTCHA widget | filled, submission refused, CAPTCHA hand-off |
| `/globex/jobs/4004` | a form with "Signature (type your full name)" | filled *except the signature*, submission refused, signature hand-off |

## The flow

**0. The auth gate first.** `POST /api/job-postings/{id}/autofill` with no
`Authorization` header must return `401`, and no browser may open. It runs
first deliberately: if the gate ever stops holding, the run fails before a
browser is ever pointed at a form on someone's behalf.

**1. Fill the form** (criterion 1). One `POST
/api/job-postings/{id}/autofill`, and the response is the whole form in page
order. Asserted:

- the standard fields carry the profile's values — first/last name, email,
  phone, location, LinkedIn — and the name, which was split out of the single
  stored `full_name`, comes back `is_derived: true` while values read
  verbatim do not;
- the seeded resume is `attached` as `dana-whitfield-resume.pdf`, and the
  cover letter's stored text is pasted into the textarea;
- the two legal questions are answered exactly ("Yes" to authorization, "No"
  to sponsorship) and both are `requires_confirmation`;
- both EEO questions are `surfaced` with `reason:
  requires_candidate_answer`, `value: null`, and
  `sensitivity: voluntary_self_id`;
- the company's screening question is `surfaced` as `unrecognized` and, being
  required, is the sole entry in `unanswered_required_fields`;
- a screenshot came back, and `review_session_id` names the parked form the
  candidate will submit through.

**2. Submission is refused twice, and each refusal is actionable**
(criterion 4). With no confirmations, `POST
/api/autofill-sessions/{id}/submit` returns `409` naming both unconfirmed
legal answers. With confirmations but the screening question still blank, it
returns `409` naming that question. After each, the portal's recorded
submissions are asserted **empty** — nothing was sent while anything was
outstanding.

**3. The candidate answers what only they can** (criteria 1 and 3). `POST
/api/autofill-sessions/{id}/fields/{field_id}` twice:

- the screening question, which clears `unanswered_required_fields`;
- **one** of the two EEO questions, because they chose to. It comes back
  `answered_by_candidate: true` and `requires_confirmation: false` — a value
  the candidate just typed is already their own statement, so a confirmation
  gate pointing at it would point at nothing.

**4. The candidate submits** (criterion 4). `POST
/api/autofill-sessions/{id}/submit` with the confirmations returns `200`, and
the receipt says what was pressed ("Submit application"), where the portal
left the browser, and what it said back. Then the recorded submission is
checked field by field — see below. Submitting the same review again returns
`404`, and the portal's count of received applications stays at one.

**5. The three hard boundaries** (criterion 2). Each on its own form:

- **login** — `requires_handoff: true`, `fields: []`, no review session, and
  `stopped_autofill: true`. Nothing was typed into the sign-in form, and the
  portal received no sign-in POST. The page behind a login prompt is not the
  application form, and filling it would put the candidate's details into an
  account they may not have.
- **CAPTCHA** — the form *is* filled (`First Name` carries the candidate's
  name), because the form around a challenge is real and filling it is most
  of the value. What the challenge costs is the in-app submit:
  `can_be_submitted_here: false`, and the submit route returns `409` carrying
  the boundary, the apply URL, and the instruction to finish it in their own
  browser. The portal received nothing.
- **signature** — the signature field is `surfaced` with
  `reason: requires_candidate_signature` and `value: null`, while the rest of
  the form fills. Submission is refused the same way, and the portal received
  nothing.

## The signature case is the sharpest one

`Signature (type your full name)` is an ordinary text input, and its label
reads to the field recognizer as a request for the candidate's full name —
which ApplyFlow has on file and can answer. Filling it would mean **signing
the application for them**, and a hand-off that refuses to submit *after*
signing would be worse than no hand-off at all.

So the boundary rules are enforced twice, at two different levels, from one
vocabulary:

- `detect_application_boundaries` recognizes the page as carrying a signature
  request and blocks submission;
- `is_signature_field` (same phrase list) makes the planner refuse the field
  itself, before recognition runs.

The acceptance check asserts both halves: the signature field is empty *and*
the submission is refused.

## Sensitive fields: what the portal actually received

This is criterion 3, and the two EEO lines are the whole of it. The seeded
candidate has a **complete** EEO record on file — gender *and* veteran status
— precisely so that having it can be shown to change nothing.

From the run that gated this check, the local portal's record of the one
application it received:

```
job_application[first_name]                   = 'Dana'
job_application[last_name]                    = 'Whitfield'
job_application[email]                        = 'epic05-candidate-…@example.com'
job_application[phone]                        = '512-555-0148'
job_application[location]                     = 'Austin, Texas'
job_application[urls][LinkedIn]               = 'https://www.linkedin.com/in/danawhitfield'
job_application[cover_letter_text]            = 'Dear Cobalt Grid Systems team,…'
job_application[answers][why]                 = 'I have run event-processing services in production…'
job_application[answers][work_authorization]  = 'Yes'
job_application[answers][sponsorship]         = 'No'
job_application[eeo][gender]                  = 'Female'
job_application[eeo][veteran_status]          = <empty>
job_application[resume]                       = dana-whitfield-resume.pdf (1285 bytes)
```

Read the last three lines together:

- **`work_authorization` and `sponsorship` carry answers** because the record
  states them, the candidate stated them themselves
  (`WorkAuthorization.ATTESTING_SOURCES` refuses a status parsed out of a
  resume), and they confirmed them before submitting. Leaving a required
  authorization question blank stalls an application, so silence is not the
  safe default here — answering *approximately* is what is unsafe.
- **`gender` carries the candidate's own answer**, typed on this application,
  in step 3. Not the profile's stored value, which was never consulted: the
  same string happens to be what they chose, and the path it travelled is
  what matters.
- **`veteran_status` is empty**, even though the profile answers it. That
  single blank field is criterion 3: disclosure is voluntary and is a decision
  made per application, so an autofill carrying last week's answer forward
  would quietly convert one disclosure into a standing one, and the candidate
  would never see it happen. Leaving the question alone is itself their
  decision, and it is honoured.

The resume line is worth noting too: it is a real multipart upload, parsed out
of the recorded request body, and its bytes start with `%PDF`. The PDF is
rendered from the stored snapshot at fill time, so what a recruiter would
download is the document that was archived.

## What makes "nothing is submitted unattended" structural

Four things, all checked here:

1. **Submission is a separate request** the candidate makes, on a review
   session id, carrying their confirmations. There is no flag on the autofill
   route that submits, no route that fills and sends in one step, and nothing
   scheduled or queued that can reach `SubmitApplicationForm`.
2. **The gates are re-checked against the live page**, not against the report
   the client is holding — which is how a CAPTCHA that appeared *after* the
   form was filled still stops the submission.
3. **The confirmations are a required input, not a defaulted flag.** A
   missing `confirmed_field_ids` means "nothing is approved" (asserted in the
   controller tests), because the opposite default would send legal
   declarations nobody had looked at.
4. **The button that will be pressed is never guessed.** One submit control
   is pressed; several means the candidate must name which, since "Submit
   application" and "Submit and create an account" are both submissions and
   choosing would pick a side effect they never agreed to; none means the
   portal submits from script the harness cannot see, and the answer is a
   hand-off rather than clicking the nearest button-shaped thing.

## Known limitations, stated rather than hidden

- **Review sessions are process-local.** A parked review holds a live browser
  session, so it lives in the process that opened it. An API served by
  several workers needs sticky routing for the review flow, or a request that
  lands on another worker gets `ReviewSessionNotFoundError` — the same honest
  "run it again" an expired review gets, never a silent misfill. The
  alternative design (re-open the portal and re-fill on submit) means filling
  a real application form twice.
- **A post-press challenge cannot be recovered from.** If the portal answers
  a submission with a CAPTCHA, `outstanding_boundaries` says so and
  `is_confirmed_sent` is `false`; the candidate finishes in their own
  browser, and the values ApplyFlow typed do not transfer. Refusing *before*
  the press (the common case) is what the pre-flight scan is for.
- **Jurisdiction on the legal questions.** `WorkAuthorization` does not
  record which country its status refers to, so "authorized to work in the
  United States?" is answered from the record as the candidate's answer to
  the standard question. The confirmation gate is the safeguard until that
  data-model change lands (Epic 01); see `decide_sensitive_field`.
- **The review screen is not covered by this check.** The flow is proven
  through the API, which is where every gate lives.
  `frontend/src/components/AutofillReview.tsx` renders it — the fields in page
  order, the screenshot, a confirmation box per legal declaration, an answer
  box per surfaced question, and a Submit button disabled on the same two
  lists the backend refuses on (`fields_awaiting_confirmation`,
  `unanswered_required_fields`). It is deliberately not a second
  implementation of the gates: a UI that computed them itself would
  eventually offer a button the backend refuses. The repo has no frontend
  test harness, so that screen is verified by `npm run build` and
  `npm run lint` only.
- **Not yet in the container images.** The `Dockerfile` installs the
  Playwright wheel but not the browser. Whoever wires this into a container
  adds `playwright install --with-deps chromium` and sets
  `BROWSER_LAUNCH_ARGS=["--no-sandbox"]`.

## Covered elsewhere, not repeated here

- **The mapping rules per platform** (Lever's control names, Ashby's
  `_systemfield_` ids, every surface reason) — `tests/domain/test_ats_field_mapper.py`,
  `tests/application/test_autofill_application_form.py`. This check proves the
  Greenhouse path against real HTML rather than re-enumerating three
  platforms' markup.
- **The boundary rules themselves** — which markers count, and the false
  positives that must not fire (the boilerplate "constitutes an electronic
  signature" paragraph, a `captcha-free-hiring` class name, a `redirect_to=/login`
  query parameter) — `tests/domain/test_application_boundary_detector.py`.
- **Every submit-gate refusal in isolation**, including the ones this flow
  cannot easily provoke (an ambiguous submit button, a form with nothing
  pressable, a press that fails) — `tests/application/test_submit_application_form.py`.
- **The harness's own guarantees** — that `read_fields` returns no buttons,
  that a field handle cannot press anything, that a press invalidates every
  handle — `tests/infrastructure/test_playwright_browser_automation.py`, also
  against a real Chromium.

## Cleanup

The candidate profile is deleted in a `finally` block, and every browser this
run opened is closed through `shutdown_portal_automation()`. The four seeded
postings and the two document snapshots are left in place deliberately —
neither `JobPostingRepository` nor `ApplicationDocumentRepository` exposes a
delete method (a record of what was sent must not be erasable; see
`ApplicationDocument`) — the same convention `test_epic03_matching_pipeline.py`
and `test_epic04_tailoring_pipeline.py` follow.
