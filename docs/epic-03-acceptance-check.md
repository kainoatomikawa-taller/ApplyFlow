# Epic 03 acceptance check — job matching pipeline

Epic 03 built the matching pipeline: requirement extraction and
hard/soft classification, hard-disqualifier filtering against a
candidate's profile, fit-score + rationale + gap-list generation, the
final ranked list, and the thumbs-up/down feedback loop. This document is
the Definition of Done for that epic and the flow
`tests/acceptance/test_epic03_matching_pipeline.py` proves end to end
against real infrastructure.

## What "done" means

1. For a test user and a job set, the engine returns a ranked list of
   matches, each with a fit score, a "why this fits" rationale, and a
   gap list.
2. Filtering excludes only genuine hard disqualifiers — a role a
   candidate could actually reach is never filtered out just because its
   description *mentions* a stretch requirement as a preference.
3. Thumbs-up/down feedback on a match is recorded and retrievable
   through the data-access layer.

## The "PhD role vs sophomore" case

The sharpest test of criterion 2 is a candidate with only a high-school
diploma (a "sophomore") against two postings that both mention a
doctorate:

| Posting | Doctorate stated as... | Expected outcome |
| --- | --- | --- |
| Senior Research Scientist | **required** (`degree_required=True`) | filtered out — a genuine hard disqualifier |
| Junior Software Engineer | **preferred** (`degree_required=False`), Python wanted | stays in the ranked list — a reachable role; the PhD mention shows up as a *gap*, not a rejection |

Both directions matter: failing to filter the first would waste the
candidate's time on an unreachable role; over-filtering the second would
hide a job they could actually get — the dominant failure mode
`HardDisqualifierFilter` is deliberately built against (see that domain
service's docstring).

## Running it

The check is opt-in — it hits a real Postgres database, the real HTTP
app with real Supabase-JWT auth, and makes one real (cheap-tier)
Anthropic call to generate the reachable posting's rationale:

```bash
RUN_EPIC03_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic03_matching_pipeline.py -v -s
```

Requires, via `.env` or exported env vars:

- `DATABASE_URL` — a reachable Postgres (`docker compose up db` locally, or a Supabase project)
- `SUPABASE_JWT_SECRET` — used both to mint the test's bearer token and by the app to verify it
- `ANTHROPIC_API_KEY` — a pay-as-you-go key (see `AnthropicLlmClient`)

Without `RUN_EPIC03_ACCEPTANCE_TEST=1` set, the test is skipped — the
regular `pytest` run never touches a real database or spends money.

## What the flow does

1. **Seed one candidate + two postings directly through the repositories**
   (`SqlAlchemyProfileRepository`, `SqlAlchemyJobPostingRepository`) —
   this check exercises the matching engine, not job ingestion, so the
   job set is hand-built rather than pulled from an aggregator.
   - The candidate: `highest_degree=HIGH_SCHOOL`,
     `work_authorization=CITIZEN`, one skill (`Python`).
   - The disqualifying posting: `degree_level=DOCTORATE`,
     `degree_required=True`.
   - The reachable posting: `degree_level=DOCTORATE`,
     `degree_required=False`, `required_skills=("Python",)`.
2. **`GET /api/job-postings/matches`** with a real bearer token — asserts:
   - the disqualifying posting's id is absent (criterion 2, the
     under-filtering side — a genuine gate is actually enforced)
   - the reachable posting's id is present (criterion 2, the
     over-filtering side — a soft mention doesn't exclude it)
   - its entry carries a numeric `score` (0-100), a non-empty `rationale`
     (the real LLM call), and `"Doctorate preferred"` in `gaps`
     (criterion 1)
   - the same route rejects a request with no `Authorization` header
     (401), proving the auth gate is live, not bypassed
3. **`POST /api/job-postings/{id}/feedback`** with `thumbs_up` and the
   score from step 2, then **`GET /api/job-postings/feedback`** — asserts
   the submitted reaction comes back with the same job id, rating, and
   score (criterion 3).

## Cleanup

The candidate profile is deleted in a `finally` block. The two seeded job
postings and the recorded feedback row are left in place deliberately —
`JobPostingRepository` and `JobMatchFeedbackRepository` don't expose a
delete method (postings and feedback are long-lived/append-only by
design; see their docstrings) — the same convention
`test_epic00_skeleton.py` follows for the usage-log rows it writes.

## Tuning-signal path (documented, not exercised here)

Feeding recorded feedback back into scoring runs through
`ScoringFeedbackAnalyzer` (`src/domain/services/scoring_feedback_analyzer.py`)
and the `GET /api/job-postings/feedback/analysis` endpoint it backs — this
acceptance check proves feedback is recorded and retrievable (criterion
3); the analysis path itself is covered by
`tests/application/test_analyze_scoring_feedback.py` and
`tests/domain/test_scoring_feedback_analyzer.py` rather than repeated
here.
