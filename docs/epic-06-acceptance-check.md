# Epic 06 acceptance check — the tracker

Epic 06 is the part of ApplyFlow that remembers. It turns the act of
submitting into a permanent record of *what was sent to whom*, follows that
application through whatever becomes of it, and feeds the answer back into
matching so a role the candidate already applied to stops being suggested.
This document is the Definition of Done for that epic, and the flow
`tests/acceptance/test_epic06_tracker_pipeline.py` proves it end to end
against a real Postgres and the real HTTP app.

## What "done" means

1. A submitted application is logged with its exact sent documents.
2. Its status can be updated and reflects correctly in the UI.
3. An already-applied role is not nudged for re-application.
4. The flow is documented as the Epic 06 acceptance check — this file.

## Running it

The check is opt-in — it writes to a real database:

```bash
RUN_EPIC06_ACCEPTANCE_TEST=1 \
  pytest tests/acceptance/test_epic06_tracker_pipeline.py -v -s
```

Requires, via `.env` or exported env vars:

- `DATABASE_URL` — a reachable Postgres (`docker compose up db` locally, or a
  Supabase project)
- `SUPABASE_JWT_SECRET` — used both to mint the test's bearer tokens and by
  the app to verify them, so the run proves the real auth path
- `ANTHROPIC_API_KEY` — needed only by the matched-jobs route. Nothing in the
  tracker itself calls a model; the route's rationale generator is built
  eagerly in the composition root, so criterion 3 cannot be checked without a
  key. The cost is two cheap-tier calls, because a suppressed posting is
  dropped *before* any rationale is generated — which is itself one of the
  properties being demonstrated.

No browser. Without `RUN_EPIC06_ACCEPTANCE_TEST=1` the test is skipped and an
ordinary `pytest` run never touches a database.

## Why there is no browser here, and why that is the right scope

The tracker is written by the act of submitting, and submitting on a real
portal is what Epic 05's check already proves — against a real Chromium, a
real ATS-shaped form, and a real recorded POST body. Re-driving that here
would re-prove someone else's epic and would make this check depend on a
browser it has nothing to say about.

So this check starts from Epic 05's **artifact**: a real `ApplicationReview`
row, seeded through the real repository, in the state Epic 05's flow leaves
one in. Everything from the submission onward is production code — the real
`POST /api/application-reviews/{id}/submit`, the real `SubmitApplicationReview`,
the real `SubmittedApplicationLog`, the real SQLAlchemy repositories, the real
tracker routes, and the real matching route. It is the same convention
`test_epic04_tailoring_pipeline.py` follows when it seeds Epic 03's output
rather than re-ranking a job set.

## The setup, and the two controls in it

One candidate, and **two** postings they qualify for:

| Posting | Role | What it is for |
| --- | --- | --- |
| `epic06-job-applied-…` | Senior Platform Engineer @ Globex, Austin, Texas | the one they apply to |
| `epic06-job-control-…` | Staff Backend Engineer @ Initech, Austin, Texas | the control |

Both are in the matched list *before* anything is sent, and that assertion is
made explicitly. Without it, "the applied-to role disappeared" would be
consistent with the matched list being empty for some unrelated reason — a
disqualifier, an inactive posting, a broken query. The control is what makes
the later absence mean suppression.

Two documents are archived for the applied-to posting before submission: the
tailored résumé and the cover letter, the snapshots Epic 04 produces.

## The flow

**0. The auth gate first.** `GET /api/tracked-applications` and the status
`PATCH`, both with no `Authorization` header, must return `401`. It runs first
deliberately: a tracker is a record of where someone is applying for work, and
if the gate ever stops holding, the run fails before a row of it is read.

**1. The control.** The tracker is empty, and both postings are in
`GET /api/job-postings/matches`.

**2. The candidate submits** (criterion 1).
`POST /api/application-reviews/{id}/submit` returns `200`, and the review comes
back `submitted_by_user` with a `submitted_at`.

**3. A newer résumé is archived afterwards.** The candidate revises their
résumé for the same job the next day. Nothing sends it anywhere. It exists so
that the failure this epic's whole design guards against — the tracker showing
today's document instead of the one that went out — would be *caught* rather
than assumed impossible.

**4. What the tracker logged** (criterion 1). `GET /api/tracked-applications`
returns exactly one row, and it is checked field by field:

- the role, company, and location are the posting's, copied at record time;
- `applied_at` is the submission's own timestamp, not the moment of the read;
- `status` is `applied` and `is_open` is true;
- `resume.id` is the **v1** snapshot, `resume.version == 1`, and its
  `content_sha256` matches the archived document — and it is asserted
  explicitly *not* to be the v2 revision archived in step 3;
- `cover_letter` is the archived letter;
- the row carries no document text at all;
- `status_history` holds exactly one entry — `applied`, with a null
  `previous_status` — because nothing has happened to it yet, and
  `current_status_since` equals the submission time.

Then the references are **followed**: each id is read back through
`GET /api/application-documents/{id}`, and the returned `content` is compared
against the exact string that was archived, digest included. That is the
difference between asserting *about an id* and proving the claim — "these are
the exact documents that were sent" is only true if the reference resolves to
the bytes that went out, so the check resolves it.

**5. The status is maintainable** (criterion 2). `PATCH
/api/tracked-applications/{id}/status`:

- `applied → interviewing`, with the candidate's own note, returns `200`. The
  response carries the *next* set of `allowed_next_statuses` (`offer`,
  `rejected`, `withdrawn`), and the move is **recorded rather than merely
  applied**: `status_history` grows by an entry naming where it came from and
  carrying the note, and `current_status_since` moves off the submission date;
- the change is then re-read through `GET /api/tracked-applications` — the
  same route the tracker screen renders from — because a write that only
  reports success has not been shown to reflect anywhere;
- the re-read also confirms the status change did not disturb the document
  references;
- `"ghosted"` is `422`: not a status at all;
- `interviewing → applied` is `409`: a real status, not a legal move, and the
  re-read confirms nothing was written;
- `→ draft` is `422`, not `409`: `draft` is a real status but not one this
  record can ever hold, so the answer is "that is not a value for this field",
  and the message names what to do instead (a draft is an `ApplicationReview`);
- `→ rejected` returns `200`, `is_open` becomes false, and
  `allowed_next_statuses` is empty — which is how a client knows to render the
  status as settled rather than as a control that cannot do anything. The whole
  path it took (`applied → interviewing → rejected`) is still on the record: a
  tracker that kept only the current status could not answer "how long was I in
  play before they passed?".

**6. The role is not nudged again** (criterion 3).
`GET /api/job-postings/matches` no longer contains the applied-to posting, and
still contains the control. The application is in `rejected` at this point,
which is deliberate: suppression does not consult status, and a rejection is
the strongest possible reason not to suggest applying again.
`?include_already_applied=true` returns both, with `already_applied: true` on
the one and `false` on the other — the flag a client needs to render a "you
already applied" section rather than silently mixing them back in.

**7. Submitting again changes nothing.** A second
`POST /api/application-reviews/{id}/submit` is `409`, the tracker still holds
exactly one row, and the replay moved neither the recorded `applied_at` nor
the status the candidate has since set.

**8. Another candidate sees none of it.** A second bearer token reads an empty
tracker, and a `PATCH` against the first candidate's application is `404` —
not `403`. The two are indistinguishable on purpose: a distinct "not yours"
would confirm that an id the caller was handed is real.

## The sharpest assertion is step 3 and 4 together

Everything else in this check would pass against a tracker that resolved
documents with `get_latest(user_id, job_posting_id, kind)` — which is the
natural thing to write, and is the right question to ask *at send time*. It is
the wrong question afterwards. A candidate who revises their résumé has a
newer version stored against the same job, and a tracker that read it would
show a document the employer never received, with no indication that anything
had changed.

That is why `TrackedApplication` stores `resume_document_id` rather than
deriving it, why `ListTrackedApplications` follows the id rather than calling
`get_latest`, and why this check archives a v2 it never sends. The assertion
`row["resume"]["id"] != later_revision.id` is the one that fails if that
design is ever quietly undone.

## The UI, and what "reflects correctly" is checked against

`frontend/src/components/ApplicationTracker.tsx` renders the feed: one row per
application, the sent documents by version and digest, a status control, and
the status history behind a disclosure once an application has moved.

The check proves criterion 2 through the API rather than through the screen,
because that is where the rule lives — and the component is written so those
are the same thing:

- the status control's options are `allowed_next_statuses` **from the
  response**, which is `ApplicationStatus.allowed_transitions` passed through
  the use case unchanged. A dropdown that listed every status would offer
  "back to interviewing" on a rejected application, and the candidate would
  meet the `409` only after choosing;
- when that list is empty the status renders as text, not as a control that
  cannot do anything;
- a successful `PATCH` replaces the row with **what came back**, rather than
  patching it locally, so the screen shows the stored outcome rather than the
  candidate's intent.

The repo has no frontend test harness, so that screen is verified by
`npm run build` and `npm run lint` only — the same limitation Epic 05's check
states about its review screen.

## Known limitations, stated rather than hidden

- **Status changes are the candidate's own observation.** Nothing infers them.
  An interview invitation arrives in the candidate's inbox, not in ApplyFlow,
  and a tracker that guessed at outcomes would state things about an
  employer's decision that nobody told it.
- **A broken document reference degrades rather than fails.** The write path
  refuses to create one and `ON DELETE RESTRICT` refuses to break one, so a
  null `resume` on a row means something has gone wrong beneath both. It is
  reported as a row with an empty reference and an ERROR log rather than an
  exception, because one unreadable row must not hide the candidate's entire
  history — what was sent is missing, but *that they applied* is not, and that
  is the fact suppression depends on. Covered by
  `tests/application/test_tracked_application_use_cases.py`, not here.
- **Suppression is exact, not fuzzy.** "Backend Engineer" and "Backend
  Engineer II" stay distinct roles. Suppression *removes* things from the
  candidate's view, so it fails toward showing one job too many rather than
  hiding one they never applied to. The identity rules are
  `tests/domain/test_canonical_job_identity.py`.
- **Nothing is cleaned up but the profile.** The seeded postings, the two
  document snapshots, the review, and the tracked application are left in
  place: none of those repositories exposes a delete, because a record of what
  was sent must not be erasable. Erasing a candidate's history is Epic 07's
  deliberate, user-scoped purge. Same convention as Epic 03, 04, and 05.

## Covered elsewhere, not repeated here

- **Logging idempotency under concurrency** — the read-then-insert race, the
  unique constraint refusing the loser, and the loser returning the winning
  row: `tests/application/test_submitted_application_log.py`.
- **A logging failure never failing a submission** —
  `tests/application/test_submit_application_review_logging.py`.
- **The entity's own rules** — that a sent document reference cannot be
  repointed, that the wrong job's or another candidate's document is refused,
  that `draft` is refused: `tests/domain/test_tracked_application.py`.
- **The suppression rule against the real ingestion dedup key**, including the
  case where Epic 02 legitimately keeps two rows for one role from two sources
  and matching suppresses both: `tests/application/test_applied_job_suppression.py`.
- **The tracker against a real database** — a status transition, a dangling
  reference refused at write time, and a delete of an applied-to posting
  refused: `tests/infrastructure/test_tracked_application_persistence_smoke.py`.
- **The status lifecycle in isolation** — every transition, the history it
  builds up, the `statuses` / `open_only` filters being pushed into the query
  rather than applied over the results, and ownership on every read:
  `tests/application/test_application_status_tracking.py`. What the reads say
  about the *documents* is the complement, in
  `tests/application/test_tracked_application_use_cases.py`.
- **Every route refusal in isolation** —
  `tests/interfaces/http/test_tracked_application_controller.py`.
