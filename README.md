# ApplyFlow

**AI-assisted job application tracking & tailoring.**

ApplyFlow lets candidates track job applications through their lifecycle and
uses an LLM (via LangChain) to score a resume against a job description and
draft a tailored cover letter. Heavy AI work runs asynchronously through
Celery + Redis, and data is persisted in PostgreSQL.

## Tech Stack

| Layer        | Technology                                   |
| ------------ | -------------------------------------------- |
| Backend API  | Python 3.11, FastAPI, Uvicorn                |
| Frontend     | React 18, TypeScript, Vite                   |
| Database     | PostgreSQL (SQLAlchemy async + Alembic)      |
| AI           | LangChain + OpenAI                           |
| Async jobs   | Celery + Redis                               |
| Portal automation | Playwright (headless Chromium)          |
| Packaging    | Docker, docker-compose                       |

---

## Application shell

The web app (`frontend/`) is the primary shell — the CLI
(`src/interfaces/cli/`) is a secondary adapter for scripting and dev
checks. See [ADR 0001](docs/decisions/0001-application-shell-web-vs-cli.md)
for the decision and rationale (Epic 5's review-and-submit UI is
inherently visual, which drove the choice).

Both adapters select their environment through config rather than
hardcoded endpoints: the backend reads `ENVIRONMENT` via
`src/infrastructure/config.py`, and the frontend reads `VITE_API_URL` via
`frontend/.env` (copy from `frontend/.env.example`). Opening the app shows
a "hello world" status banner that calls `GET /health` and displays which
environment the API is running in, proving the shell is wired end-to-end
before any feature UI loads.

### Tailoring review UI

"Tailor & review" on a matched role opens the two-step review flow
(`frontend/src/components/TailoringReview.tsx`):

1. **Gap questions** (`GapQuestionLoop`) — one question at a time against the
   match's gap list, with "nothing to add" given the same weight as
   answering, because `GapAnswerPolicy` treats a decline as a clean omission
   and a UI that buried it would coax the embellishment the backend refuses
   to store. Gaps a remembered answer already covers come back as
   *already answered* and are never re-asked.
2. **Document review** (`DocumentReviewPanel`) — the tailored resume and
   cover letter, each editable in place. Saving posts to the revision route,
   so the stored version is the edited one; lines the guard removed from that
   edit are shown rather than silently dropped. `TailoringSummary` says what
   was tailored for the job: which of the posting's listed skills the
   document mentions (and which it does not), which gap answers it drew on,
   and which of the candidate's own data the surviving content traces to.
3. **Review and submit** (`AutofillReview`) — fills the employer's own form
   in a real browser and shows it back: every field in page order with what
   was written, the screenshot of the filled form, a confirmation box on each
   legal declaration, and an answer box on each question ApplyFlow refused to
   guess at (including EEO, which reaches a form this way or not at all).
   Submit is disabled on the same two lists the backend refuses on, and a
   hand-off — a login wall, a CAPTCHA, a signature request — is rendered as
   what to do next rather than as an error. It comes third because the
   autofill attaches the *stored* documents from step 2.

3. **Portal check / hand-off** (`PortalHandoffPanel`) — "Check the portal"
   reads the posting's application form *without touching it*. A clean portal
   reports its questions; a portal with a hard boundary reports the hand-off
   instead: which boundary, why ApplyFlow refuses to do it, what the candidate
   has to do, the evidence it matched on the portal's own page, and a link to
   the exact URL automation stopped on. Two exits, both real — "I've done it —
   continue" and "I'll finish this one myself".

4. **Review & submit** (`ReviewAndSubmit`) — the filled application, every field
   editable, and a submit button only the candidate can press. Each answer shows
   who put it there ("filled by ApplyFlow" / "your answer" / "you declined") and,
   where ApplyFlow left a field alone, why. Sensitive fields and EEO
   self-identification are flagged and cannot be skipped: each needs a confirm,
   an edit, or a decline before submission is possible. An open hard-stop
   hand-off is presented here too, with its resume instructions, and blocks
   submitting. See "Review & submit (the user is the submitter)" below.

Every route the flow touches is authenticated, so the shell carries an access
token field (`AccessTokenField`) that stores a Supabase token in
`localStorage` — the placeholder until a real password sign-in screen lands.

## Clean Architecture

This project follows **Clean Architecture**. Source code lives under `src/`
split into four layers. **Dependencies only ever point inward.**

```
interfaces  ──►  application  ──►  domain
infrastructure ─►  application  ──►  domain
```

### `src/domain/` — the core (depends on nothing)
Pure business logic with zero third-party imports.
- `entities/` — `JobApplication` (aggregate root, protects its own invariants);
  `TrackedApplication` (aggregate root — one application the candidate
  actually sent, and the spine of the tracker; see "Application record data
  model" below); `UserProfile` (aggregate root — a candidate's contact info
  plus their `WorkHistoryEntry`, `EducationEntry`, and `Skill` child
  entities — the data spine matching, tailoring, and autofill read from);
  `Resume` (an uploaded resume file's metadata + extracted text — enforces
  the accepted file formats and size limit; see "Resume upload & file
  handling" below)
- `value_objects/` — `ApplicationStatus` (state machine), `EmailAddress`,
  `MatchScore`, `ProficiencyLevel`, `ProvenanceSource` (source tag required
  on every stored fact — see "Provenance tagging" below)
- `repositories/` — `JobApplicationRepository`, `TrackedApplicationRepository`,
  `ProfileRepository`, `ResumeRepository` **interfaces** (WHAT, not HOW)
- `services/` — `ApplicationRankingService` (pure domain logic)
- `exceptions.py` — domain exceptions

### `src/application/` — use cases (depends only on domain)
Orchestrates the domain to fulfill use cases. No DB, HTTP, or LLM code.
- `use_cases/` — one class per use case, each with an `execute(dto)` method
  (`CreateJobApplication`, `AnalyzeJobApplication`, `SubmitJobApplication`,
  `ListCandidateApplications`, `GetLlmCompletion`, `UploadResume`, `GetResume`,
  `ListResumes`)
- `dtos/` — input/output contracts (entities never cross the boundary)
- `ports/` — outbound abstractions (`ResumeAnalyzerPort`, `TaskQueuePort`,
  `IdGeneratorPort`, `AuthVerifierPort`, `LlmClientPort`, `FileStoragePort`,
  `TextExtractorPort`) implemented by infrastructure
- `mappers/` — domain ↔ DTO translation

### `src/infrastructure/` — implementations (depends on domain + application)
All I/O lives here. Implements the interfaces defined further in.
- `persistence/` — SQLAlchemy models + `SqlAlchemyJobApplicationRepository`,
  `SqlAlchemyProfileRepository`, and `SqlAlchemyResumeRepository` (implement
  the domain repository interfaces, map rows ↔ entities)
- `llm/` — `LangChainResumeAnalyzer` (implements `ResumeAnalyzerPort`) and
  `AnthropicLlmClient` (implements `LlmClientPort` — the app's single LLM
  integration; see below)
- `tasks/` — Celery app, tasks, and `CeleryTaskQueue` (implements `TaskQueuePort`)
- `services/` — `UuidIdGenerator` (implements `IdGeneratorPort`)
- `auth/` — `SupabaseJwtVerifier` (implements `AuthVerifierPort`)
- `storage/` — `LocalFileStorage` (implements `FileStoragePort`; see "Resume
  upload & file handling" below)
- `text_extraction/` — `ResumeTextExtractor` (implements `TextExtractorPort`
  with `pypdf` / `python-docx`)
- `config.py` — the **only** place environment variables are read

### `src/interfaces/` — entry points (depends on application)
Thin adapters that translate external input into use case calls.
- `http/` — FastAPI app, controllers, request/response schemas
- `http/dependencies.py` — the **composition root** where concrete
  infrastructure adapters are injected into abstract ports
- `cli/` — a command-line entry point demonstrating a non-HTTP adapter

> The dependency rule is enforced by convention and documented in each
> layer's `CLAUDE.md`, plus `architecture.json` at the repo root.

---

## Provisioning the database & auth (Supabase)

Local development runs against the Postgres container in `docker-compose.yml`
by default — no external account is needed to hack on the app. Staging and
production point at a [Supabase](https://supabase.com) free-tier project
instead, which provides both the Postgres database and the single-user auth
provider.

1. Create a free project at supabase.com (Dashboard → New project).
2. **Database connection** — Project Settings → Database → Connection string
   → "Transaction pooler" (asyncpg-compatible). Convert it to the
   `postgresql+asyncpg://` scheme and append `?ssl=require`, then set it as
   `DATABASE_URL`:
   ```
   DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?ssl=require
   ```
3. **Auth** — Authentication → Providers → enable Email, then Authentication →
   Users → add the one user this app supports. Copy Project Settings → API →
   values into:
   ```
   SUPABASE_URL=https://<project-ref>.supabase.co
   SUPABASE_JWT_SECRET=<Project Settings -> API -> JWT Settings -> JWT Secret>
   ```
4. Apply the baseline migration against the new database: `alembic upgrade head`.
5. The frontend authenticates via Supabase Auth's password sign-in and sends
   the resulting access token as `Authorization: Bearer <token>` on every
   `/api/applications*` request — the API verifies its signature against
   `SUPABASE_JWT_SECRET` (`src/infrastructure/auth/supabase_jwt_verifier.py`)
   before any use case runs.

No credentials are ever hard-coded — everything above is read through
`src/infrastructure/config.py` (see `.env.example`), and `SUPABASE_JWT_SECRET`
is required outside of `ENVIRONMENT=development`.

---

## LLM integration layer

`src/infrastructure/llm/anthropic_client.py`'s `AnthropicLlmClient` is the
**only** module in the codebase that talks to the Anthropic API. Every
LLM-backed feature depends on the `LlmClientPort` abstraction
(`src/application/ports/llm_client_port.py`) and receives this adapter from a
composition root — nothing else imports the `anthropic` SDK directly.

- **Auth**: a pay-as-you-go API key from
  [console.anthropic.com](https://console.anthropic.com/settings/keys), read
  from config as `ANTHROPIC_API_KEY` and passed explicitly as `api_key=` when
  constructing the client. Subscription/claude.ai login credentials are never
  used — there is no code path that reads an OAuth session or the `claude`
  CLI's stored credentials.
- **Required outside development**: like the other provider secrets,
  `ANTHROPIC_API_KEY` must be set whenever `ENVIRONMENT` isn't `development`
  (enforced in `src/infrastructure/config.py`).

### Model routing (cost control)

Callers never name a model — they pass a **task type**
(`LlmTaskType`, `src/application/ports/llm_client_port.py`) describing what
the prompt is *for*, and the layer picks the model. This keeps cost control
in one place: nobody can accidentally point a high-volume call at the
expensive model by passing the wrong string, because there's no model
string to pass.

| Task type               | Tier   | Default model                | Rationale                                   |
| ------------------------ | ------ | ----------------------------- | -------------------------------------------- |
| `extraction`              | cheap  | `claude-haiku-4-5-20251001`  | High-volume, low-ambiguity                   |
| `matching`                 | cheap  | `claude-haiku-4-5-20251001`  | High-volume, low-ambiguity                   |
| `parsing`                  | cheap  | `claude-haiku-4-5-20251001`  | High-volume, low-ambiguity                   |
| `resume_writing`           | strong | `claude-sonnet-5`             | Quality-sensitive, low-volume writing        |
| `cover_letter_writing`     | strong | `claude-sonnet-5`             | Quality-sensitive, low-volume writing        |

- **Default routing**: `TASK_TYPE_TIERS` in `llm_client_port.py` is the one
  place that maps a task type to a tier (`LlmModelTier.CHEAP` /
  `LlmModelTier.STRONG`). It's an application-layer policy decision — it
  doesn't know or care which provider/model implements each tier.
- **Overrides**: which concrete model backs each tier is config, not code —
  override via `ANTHROPIC_MODEL_CHEAP` / `ANTHROPIC_MODEL_STRONG` (e.g. to
  point "strong" at a newer Sonnet snapshot, or "cheap" at a cheaper model)
  without touching any call site. `ANTHROPIC_MAX_TOKENS` applies to both
  tiers.

Try the full path end-to-end with the CLI, which wires
`AnthropicLlmClient` → `GetLlmCompletion` (the generic use case every future
LLM feature can call through) and lets you pick the task type:

```bash
python -m src.interfaces.cli.main llm-ping --task-type extraction \
  --prompt "Say hello in one word."
python -m src.interfaces.cli.main llm-ping --task-type resume_writing \
  --prompt "Draft one sentence of a cover letter opener."
```

Unit tests (`tests/infrastructure/test_anthropic_llm_client.py`,
`tests/application/test_get_llm_completion.py`) mock the SDK so `pytest`
never makes a network call or spends money — including dedicated tests that
every cheap-tier task type resolves to the cheap model and every
strong-tier one resolves to the strong model. To prove real completions
from both tiers against Anthropic's API, run the opt-in live test with a
real key:

```bash
RUN_LIVE_LLM_TEST=1 ANTHROPIC_API_KEY=sk-ant-... \
  pytest tests/infrastructure/test_anthropic_llm_client_live.py
```

---

## Data-access layer

`src/infrastructure/persistence/database.py` owns the one process-wide
connection pool (`engine` / `async_session_factory`), so no later feature
opens its own connection. It's sized from config (`DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS`), pings a connection before
handing it out (`pool_pre_ping=True`), and disables asyncpg's server-side
prepared-statement cache (`statement_cache_size=0`) so the same code works
whether `DATABASE_URL` points at local Postgres or Supabase's PgBouncer
transaction-pooler — a plain Postgres connection ignores that setting, so
it's safe either way. `dispose_engine()` is called from the FastAPI
`lifespan` on shutdown so pooled connections are released cleanly instead
of leaking until the process exits.

Every aggregate gets typed read/write helpers the same way
`SqlAlchemyJobApplicationRepository` does: implement the domain-defined
repository interface (`src/domain/repositories/`), taking an `AsyncSession`
via the constructor and mapping rows ↔ entities — never leak an ORM model
past that class.

`tests/infrastructure/test_persistence_smoke.py` proves the whole path
against a **real** database — not a fake — by creating, reading, and
deleting a `JobApplication` row through the repository. It skips (instead
of failing) if nothing is reachable at `DATABASE_URL`, so `pytest` still
runs without Postgres up; start one locally with `docker compose up db` (or
point `DATABASE_URL` at any reachable Postgres) to have it actually run.
CI provisions a Postgres service container so it always executes there.

### Profile data model

`user_profiles` is a candidate's profile (contact info); `work_history_entries`,
`education_entries`, and `skills` each hang off it via a `profile_id` foreign
key (`ON DELETE CASCADE`, one profile → many rows). `skills` also has a
`(profile_id, name)` unique constraint so a candidate can't have the same
skill twice. `SqlAlchemyProfileRepository` loads/saves the whole aggregate —
profile plus its child entries — in one round trip; syncing a profile's
child collections on `update()` relies on SQLAlchemy's `delete-orphan`
cascade rather than manual diffing. `tests/infrastructure/test_profile_persistence_smoke.py`
follows the same real-database, skip-if-unreachable pattern as
`test_persistence_smoke.py` to create and read back a full profile.

### Standard "always-asked" application fields

`user_profiles` also carries the contact/link fields nearly every job
application asks for: a postal address (`street_address`/`city`/
`state_or_region`/`postal_code`/`country`) and portfolio/LinkedIn/GitHub
URLs. None of that is sensitive.

Work authorization/citizenship and EEO self-identification are a different
category — real PII this app must protect — so they live in their own
one-to-one tables (`work_authorizations`, `eeo_self_identifications`, each
keyed by `profile_id` as both primary key and foreign key) instead of
columns on `user_profiles`. That isolation is deliberate: it lets Epic 07
apply encryption-at-rest and restricted access to exactly those tables
without touching the general profile row. Every column on both tables is
flagged sensitive twice over — `WorkAuthorization.SENSITIVE` /
`EeoSelfIdentification.SENSITIVE` in the domain layer
(`src/domain/value_objects/`), and matching `info={"sensitive": True}` +
`comment=` metadata on the SQLAlchemy columns
(`src/infrastructure/persistence/models.py`) — so Epic 07 can find every
field requiring protection from either layer.

EEO self-identification is additionally modeled so it can never be
defaulted or auto-asserted: `UserProfile.eeo_self_identification` is
`None` until a candidate explicitly submits one via
`set_eeo_self_identification()`, and every field inside
`EeoSelfIdentification` (gender identity, race/ethnicity, veteran status,
disability status) itself defaults to `None` rather than any category
value — including the explicit "decline to self-identify" option each
enum offers, which is a real recorded choice, not an inferred one.
`tests/infrastructure/test_profile_persistence_smoke.py` proves this
against a real database: a fully-populated profile still comes back with
`eeo_self_identification is None` until it's set explicitly.

### Provenance tagging

Every fact this app stores about a candidate is labeled with where it came
from: `ProvenanceSource` (`src/domain/value_objects/provenance_source.py`)
is one of `parsed_resume` (extracted from an uploaded resume),
`user_entered` (typed directly into a form), or `answer` (given in response
to a specific question, e.g. an EEO self-ID prompt). This is baked into the
data model, not bolted on:

- **Every fact carries a source.** `WorkHistoryEntry`, `EducationEntry`,
  `Skill`, `WorkAuthorization`, and `EeoSelfIdentification` each have a
  required `source: ProvenanceSource` field — you cannot construct one
  without it, so it's enforced by the type system before it ever reaches
  the database. The scalar fields flattened directly onto the
  `user_profiles` row (`full_name`/`email`/`phone`/`headline`/`location`,
  and the `address`/`links` value objects) don't each get their own row,
  so they share grouped tags instead: `UserProfile.contact_source` (always
  required — those fields are always present) and `address_source`/
  `links_source` (required only once that group actually has data — an
  empty `Address()`/`ProfileLinks()` isn't a fact yet, so it needs no
  source; see `UserProfile._validate_optional_source`).
- **Cannot be persisted without one.** Constructing any of the entities/
  value objects above with a missing or invalid source raises
  `InvalidValueError` immediately — there is no code path that reaches
  `SqlAlchemyProfileRepository` with an unset provenance tag. The database
  schema mirrors this with `NOT NULL` `source`/`contact_source` columns
  (migration `0004_add_provenance_tagging.py`).
- **Queryable and returned with facts.** Provenance isn't a side channel —
  it's a normal typed column returned by `SqlAlchemyProfileRepository`
  alongside every fact it maps, exactly like any other field. Anything
  reading a `WorkHistoryEntry`/`Skill`/etc. off the repository gets
  `.source` for free.

**Downstream contract (Epic 04 — tailoring):** generated output (tailored
resumes, cover letters, autofilled application answers) may only assert
facts read through this data-access layer, each carrying a real
`ProvenanceSource`. Epic 04 must never fabricate a claim about a candidate
and present it as if it came from them — every generated statement has to
trace back to a `parsed_resume`, `user_entered`, or `answer` fact already
in the data model. This is documented directly on `ProvenanceSource` itself
so it stays visible to whoever implements Epic 04.

---

## Resume upload & file handling

`POST /api/resumes` accepts a resume file (PDF, DOCX, or plain text),
stores the raw bytes, extracts its text, and returns both the metadata and
the extracted text in one response — the input the parsing/matching
features further down the roadmap (and `ProvenanceSource.PARSED_RESUME`)
will read from.

- **Validation is a domain rule, not a controller check.** `Resume`
  (`src/domain/entities/resume.py`) owns `ALLOWED_CONTENT_TYPES` (PDF,
  DOCX, plain text) and `MAX_SIZE_BYTES` (10 MiB), and rejects anything
  else via `UnsupportedFileFormatError` / `FileTooLargeError`. `UploadResume`
  checks both *before* extracting text or writing bytes, so an invalid
  upload fails cheaply.
- **Text extraction is a port.** `TextExtractorPort` is implemented by
  `ResumeTextExtractor` (`pypdf` for PDF, `python-docx` for DOCX, UTF-8
  decoding for plain text). Any parsing failure — corrupt file, empty
  body, undecodable bytes — is re-raised as `TextExtractionError`, the one
  error type the use case and controller know how to handle.
- **Raw storage is a port, addressed by an opaque key.** `FileStoragePort`
  is implemented by `LocalFileStorage`
  (`src/infrastructure/storage/local_file_storage.py`), which writes each
  file under `RESUME_STORAGE_DIR` (default `./var/resumes`) keyed by a
  server-generated id — never the candidate's filename. `UploadResume`
  deletes the stored file if persisting its metadata row fails, so a
  crash never leaves an orphaned file behind.
- **No PII in logs or URLs.** The resume id (not a filename or email) is
  the only identifier ever placed in a path or an exception message —
  `GET /api/resumes/{resume_id}` takes the id from the path, never a
  query string, and `original_filename`/`extracted_text` are flagged in
  both the ORM model and the migration as "may contain PII — never log."
  Fetching another user's resume by id returns `404` (via
  `ResumeNotFoundError`), the same as an unknown id, so the endpoint never
  confirms or denies which ids exist for someone else.
- **Errors surface clearly.** The controller maps each domain/application
  exception to a distinct HTTP status: `415` for an unsupported format,
  `413` for an oversized file, `422` for a file that can't be parsed, and
  `404` for an unknown/not-owned resume id.

`tests/infrastructure/test_resume_text_extractor.py` exercises the
extractor against real (small, hand-built) PDF/DOCX files rather than
mocking the parsing libraries. `tests/infrastructure/test_resume_persistence_smoke.py`
follows the same real-database, skip-if-unreachable pattern as the other
smoke tests.

---

## Job matching pipeline (Epic 03)

Turns a candidate's profile and the active job set into a ranked,
scored, explained list — the primary output the rest of the product
consumes.

1. **Requirement extraction** (`ExtractJobRequirements`) parses a
   posting's free-text description into structured `JobRequirements`
   (degree, clearance, remote/location, work authorization, experience,
   skills) via the cheap LLM tier.
2. **Hard/soft classification** (`RequirementClassifier`) splits those
   requirements into genuine hard disqualifiers (a required degree/
   clearance, an on-site-only location, a citizenship/PR requirement)
   and soft preferences (everything else — experience, skills, and any
   wish-list item) — job descriptions are wish-lists, and treating every
   stated attribute as a hard cutoff over-filters reachable candidates.
3. **Hard-disqualifier filtering** (`HardDisqualifierFilter`,
   `ListEligibleJobPostings`) excludes only postings whose hard
   requirements the candidate's profile affirmatively fails — unstated
   profile data is never treated as a failure.
4. **Fit scoring, rationale, and gap list** (`SoftPreferenceEvaluator`,
   `GenerateJobFitRationale`) computes a 0-100 fit score from the share
   of soft preferences met, and an LLM (cheap tier) writes a short,
   honest "why this fits" rationale grounded only in the requirements the
   candidate actually meets.
5. **Ranking** (`RankMatchedJobPostings`, `GET /api/job-postings/matches`)
   assembles the final list: filtered, scored, ordered highest-fit-first,
   each entry carrying its score, rationale, and gap list. Roles the
   candidate already applied to are dropped here, matched on canonical
   identity rather than posting id — see
   [Already-applied jobs stop being suggested](#already-applied-jobs-stop-being-suggested).
6. **Feedback loop** (`SubmitJobMatchFeedback`/`AnalyzeScoringFeedback`,
   `POST /api/job-postings/{id}/feedback`,
   `GET /api/job-postings/feedback(/analysis)`) records a candidate's
   thumbs-up/down reaction alongside the job and score it was reacting
   to, and buckets that feedback by score band into an agreement-rate
   summary — the signal a future scoring-tuning pass would read from
   (see `ScoringFeedbackAnalyzer`'s docstring for the full contract).

See [`docs/epic-03-acceptance-check.md`](docs/epic-03-acceptance-check.md)
for Epic 03's Definition of Done and the end-to-end acceptance test that
proves it (`tests/acceptance/test_epic03_matching_pipeline.py`), including
the "PhD role vs sophomore" over/under-filtering case.

---

## Tailoring engine (Epic 04)

Turns a chosen job plus a candidate's record into an honest, tailored
resume and cover letter — and never into a claim the candidate cannot
back.

1. **Gap detection** (`DetectJobRequirementGaps`,
   `GET /api/job-postings/{id}/gaps`) checks every classified requirement,
   hard and soft alike, against the candidate's profile facts *and* their
   remembered answers, and flags each one nothing backs. Unlike fit
   scoring, silence counts as a gap here: this list answers "what haven't
   you established yet", not "does this disqualify you".
2. **The question loop** (`GenerateGapResolutionQuestions`,
   `POST /api/gap-resolution/questions`) phrases one deliberately neutral
   question per gap — never worded so that claiming the experience is the
   easier answer — *except* for gaps a remembered answer already covers,
   which come back as `already_answered` instead of being asked twice.
   Matching is semantic (`AnswerSimilarityMatcher` over embeddings), so an
   answer given once carries across applications that word the same
   requirement differently.
3. **Answer capture, or a clean decline** (`ResolveGapAnswer`,
   `POST /api/gap-resolution/answers`) stores a real answer as an
   `AnswerMemory` tagged `ProvenanceSource.ANSWER` — from then on it is a
   fact the engine may assert. A decline (`GapAnswerPolicy`) persists
   nothing at all: the gap is omitted rather than turned into a coerced
   "yes".
4. **Provenance-guarded generation** (`GenerateTailoredResume`,
   `GenerateCoverLetter`) assembles the candidate's full fact corpus
   (`ProvenanceFactAssembler`), generates on the strong tier, then runs
   `ProvenanceGuard` over the draft and drops every line the facts don't
   support. The posting's requirements reach the generator but never the
   guard — a requirement is what the employer wants, never evidence about
   the candidate — so a skill the posting demands cannot become
   self-justifying. If nothing attested survives, the request fails with
   `422` rather than returning a husk of headings.
5. **ATS-safe output** (`AtsSafeTextFormatter`, `AtsSafetyValidator`,
   `ResumeStructureParser`, `AtsSafePdfRenderer`) flattens the draft to
   plain text *before* guarding, so the text that ships is the text that
   was validated, then re-checks it and reports (never silently re-fixes)
   anything that got through. The plain-text, structured, and PDF exports
   are all derived from that one guarded string, so they cannot disagree.
6. **Snapshot of what was sent** (`ApplicationDocumentArchive`) stores that
   exact text as an immutable, per-job version before anything is returned
   — see "Sent-document snapshots" below.

See [`docs/epic-04-acceptance-check.md`](docs/epic-04-acceptance-check.md)
for Epic 04's Definition of Done and the end-to-end acceptance test that
proves it (`tests/acceptance/test_epic04_tailoring_pipeline.py`), including
the "asked for both, has only one" fabrication case — one posting that
demands both a skill the candidate volunteers in the question loop and one
they decline, where the first may appear in the output and the second must
not appear anywhere.

---

## Sent-document snapshots

Generating a tailored resume (`POST /api/job-postings/{id}/tailored-resume`)
or a cover letter (`POST /api/job-postings/{id}/cover-letter`) stores the
exact text that was produced, in the same use case that produced it, before
anything is returned. The tracker and interview prep read that snapshot
instead of regenerating a document: a fresh generation reads today's profile
through today's model, so it can quietly produce something the employer never
saw — and then prep a candidate for claims they never made.

- **Immutable.** `ApplicationDocument` is a frozen entity and
  `ApplicationDocumentRepository` has no `update` and no `delete`, so there
  is neither an in-process way to alter a snapshot nor a persistence method
  that would carry an alteration to the database. `content_sha256` is written
  alongside the content and verified on every read, so a row changed out of
  band (a migration, a manual `UPDATE`) is refused rather than served as
  authentic. The `job_postings` foreign key is `ON DELETE RESTRICT`: a record
  of what was sent must not vanish when a posting is pruned.
- **Versioned per job, not globally.** Regenerating for the same posting
  inserts the next version for that (user, job, kind) rather than
  overwriting, and a duplicate version is a unique-constraint error rather
  than an ambiguity the tracker has to guess about. The newest version is
  what the most recent submission carried; earlier ones stay readable.
- **Nothing is stored that the guard has not seen.** There is no route that
  archives document text as supplied — that would store content the provenance
  guard never saw and label it as sent. `ApplicationDocument` also refuses a
  snapshot with no backing provenance, so an unattested draft has nothing to
  be stored under (see `ProvenanceGuard` and `UnattestedGenerationError`).
  Two write paths satisfy that rule: the generation flows, and the revision
  route below.
- **Candidate edits go back through the guard.**
  `POST /api/job-postings/{id}/documents/{kind}/revisions` takes the text a
  candidate edited in the review UI, runs it through the same
  `ProvenanceGuard` against the same fact corpus, and archives what survived
  as the next version (`ReviseGeneratedDocument`). A claim the candidate typed
  themselves is stripped exactly as a model's invention would be, and reported
  back so the removal is visible rather than silent. Nothing is overwritten,
  so the history records both what the model produced and what the candidate
  changed it to.
- **PII.** `application_documents.content` is flagged sensitive at both the
  domain (`ApplicationDocument.SENSITIVE`) and schema level: a tailored resume
  carries full contact details and work history, and a cover letter is built
  from remembered answers (`answer_memories`, sensitive for the same reason),
  so a snapshot inherits the strictest classification of its inputs. Never
  logged — the archive logs the snapshot id and digest instead. List responses
  carry summaries without document text; the text is fetched one document at
  a time.

The tracker (Epic 06) joins on (`user_id`, `job_posting_id`) — the same pair
the generation flows write — so neither side has to backfill a link.

Only the resume's plain text is stored, and the PDF/structured exports are
re-derived from it on demand (all three already come from that one guarded
text, so they cannot disagree). Byte-exact PDF archival would go through
`FileStoragePort` and is not part of this store.

---

## Application record data model (Epic 06)

`TrackedApplication` (`tracked_applications`) is one row per application the
candidate actually sent: role, company, date applied, status, the job posting
it was made against, and references to the exact resume and cover letter that
went out with it.

- **It records a sent application, not a draft.** `applied_at` is required and
  `draft` is refused. The in-flight state already has a home —
  `ApplicationReview` is the form the candidate is still editing, one open per
  posting — and a tracker that also held drafts would answer "when did you
  apply?" with `NULL` for half its rows, putting a branch for
  non-applications into every reader.
- **Documents are referenced, never copied.** `resume_document_id` and
  `cover_letter_document_id` point at `application_documents` — the Epic 04
  snapshots above — so the tracker shows what the employer received rather
  than something regenerated to resemble it. A `TEXT` column here would be a
  second copy free to drift from the row that is supposed to be
  authoritative. The cover letter reference is nullable because plenty of
  forms never ask for one; a reference already set cannot be repointed, since
  that would rewrite what was sent.
- **The checks a foreign key cannot make live in the domain.** Any
  `application_documents.id` satisfies the constraint, including another
  job's resume or another candidate's. `TrackedApplication.record_sent` takes
  the snapshot entities and verifies each is the right *kind* and belongs to
  this candidate and this posting, so an application filed against the wrong
  document is rejected instead of quietly misstating what an employer got. An
  id that resolves to no row at all is refused at write time as
  `TrackedApplicationReferenceError`.
- **Role and company are snapshotted, not read through the posting.** They are
  copied from `JobPosting` at record time. A posting is a live row —
  re-ingested, re-normalized, retitled, eventually stale — while this one
  states what the candidate applied to *then*, so a posting edited in June
  cannot rewrite an application sent in March.
- **Status reuses `ApplicationStatus`.** Same state machine, same transition
  rules as the rest of the system, so the tracker cannot reach a different
  conclusion about whether a rejected application can go back to
  interviewing. Unlike the document store, this repository has an `update`:
  following an application through its lifecycle is the point. It has no
  `delete` — erasing a candidate's data is Epic 07's deliberate, user-scoped
  purge, not an ambient capability. Every move is also *recorded* — see
  "Status lifecycle and history" below.
- **Every foreign key is `ON DELETE RESTRICT`,** matching
  `application_documents` rather than the CASCADE on `application_reviews` and
  `portal_handoffs`. That is the same distinction those tables draw: in-flight
  state is worthless once its posting is gone, while the archived record of a
  sent application is a real event that has to outlive pruning.
- **Applying twice is two rows.** There is deliberately no unique constraint
  on (`user_id`, `job_posting_id`): a candidate who applies again months later
  has made two applications, each with its own date, documents, and outcome.
- **Not sensitive.** A role, a company, and a status carry nothing that
  `work_authorizations` or `answer_memories` do — the sensitive material sits
  in the documents this row references, behind their own flags. Which is why
  these columns are ids: the row stays loggable.

### Logging a submission into the tracker

A record is created by the act of submitting, not by a separate "add to
tracker" step. `SubmitApplicationReview` — the one path that marks an
application as sent — calls `SubmittedApplicationLog` after it persists the
submitted review.

- **Reuse, never regeneration.** The log reads the resume and cover letter
  through `ApplicationDocumentRepository.get_latest`, the documented answer to
  "the document this application went out with". The service holds no
  generator and no LLM port, so there is no path from submitting to producing a
  document — a missing resume snapshot is an error
  (`NoStoredApplicationDocumentError`), never a prompt to make one. Deliberate:
  generating at log time reads today's profile through today's model and could
  record something the employer never received.
- **Role, company, and date are derived, not passed.** The caller supplies the
  posting id and the submission time; `record_sent` copies the role and company
  off the posting itself, and the date is the `submitted_at` recorded on the
  review. None of the three can be supplied wrongly at the call site.
- **Idempotent per submission.** `submission_key` is the submitted review's id,
  and it is unique per candidate at the schema level. The log reads before it
  writes, and if two concurrent requests (a double-clicked submit) both pass
  that read, the constraint refuses the loser, which then returns the row that
  won. A replay produces the one record; it never moves the recorded date or
  resets a status that has since advanced.
- **A logging failure never fails a submission.** The review is marked
  submitted and persisted *first*; only then is the tracker written. If that
  write fails, the use case still succeeds — the candidate's application is
  with the employer, and reporting a failure would tell them something false
  about it while inviting a retry the domain refuses anyway. The failure is
  logged at ERROR with the review, user, and posting ids, and the idempotency
  above is what makes replaying it safe rather than double-counting.

`tests/infrastructure/test_tracked_application_persistence_smoke.py` proves the
path against a **real** database, the same way `test_persistence_smoke.py`
does: it archives an Epic 04 resume and cover letter, records an application
against them, reads it back, follows the reference to the snapshots to confirm
they come back byte for byte, drives a status transition, and checks that a
dangling reference and a delete of an applied-to posting are both refused. It
skips (instead of failing) when nothing is reachable at `DATABASE_URL`.

The migration is `migrations/versions/0017_create_tracked_applications.py`.

### Status lifecycle and history

An application's status changes over time, and the tracker keeps the whole
sequence rather than only where it ended up. `applied → interviewing → rejected`
is preserved as three recorded moves, because the questions the tracker exists
to answer are about *when* things changed: "applied three weeks ago, still no
reply" is a follow-up, and "the recruiter screen already happened" is interview
prep. Neither is answerable from a single status column.

- **The history is part of the aggregate.** `ApplicationStatusChange` is a value
  object; `TrackedApplication.status_history` is the list of them, oldest first.
  The invariant is that `status_history[-1].status` *is* `status`, checked on
  construction — a row where those disagree is one that two different queries
  would answer differently. `change_status` appends and reassigns in one step,
  so it is not possible to move an application without recording that it moved,
  and a refused transition raises before anything is recorded.
- **One transaction, one store.** `application_status_events` is a child table
  of `tracked_applications`, written by the same repository in the same commit.
  A separate history store with its own repository could commit the status
  without its entry, leaving a record whose present and past disagree
  permanently.
- **Append-only.** Nothing in the data-access layer updates or deletes an event
  row; `update` inserts the entries whose `sequence` is beyond what is stored.
  The primary key is (`tracked_application_id`, `sequence`) — no surrogate id,
  because a status change has no identity beyond its position in one
  application's history — and that key is what makes appending the same entry
  twice a constraint violation rather than a duplicated step.
- **Each entry names where it came from.** `previous_status` is redundant with
  the preceding row's `status` on purpose: it makes one row self-describing
  ("rejected after interviewing") and makes a corrupt history *detectable*
  rather than merely wrong. It is NULL for exactly one entry — `sequence` 0, the
  application being sent.
- **`ON DELETE CASCADE`,** the only one on the tracker. This is the one
  genuinely part-of relationship here: history without its application is
  unreadable. The application is still protected from a posting being pruned by
  the RESTRICT on `tracked_applications` itself.
- **Rows written before history existed are seeded, not guessed.** A row that
  knows its status and when it was sent *is* a one-entry history, so migration
  `0019` backfills exactly that (dated `applied_at`, no previous status), and
  the entity does the same for any row that still arrives with an empty history.
- **Status is queryable.** `list_by_user_id(statuses=...)` filters in SQL
  against the existing (`user_id`, `status`) index, so the tracker's views do
  not get slower as a search gets longer. An empty collection matches nothing —
  the honest reading of "none of these statuses", distinct from no filter at
  all. `open_only` on the use case resolves the live statuses from
  `ApplicationStatus.is_terminal` rather than keeping a second list of them.
- **Notes are the candidate's own words.** Optional free text per change
  ("recruiter screen booked for the 14th"), capped at 1000 characters. Not
  sensitive the way a document is, but it is whatever they typed, so it stays
  out of logs — status transitions are logged by status and id only.

The HTTP surface is `tracked_application_controller`:

| Route | What it does |
| --- | --- |
| `GET /api/tracked-applications` | The feed, newest first. `?status=` (repeatable) or `?open_only=true`. |
| `GET /api/tracked-applications/{id}` | One application with its full history. |
| `PATCH /api/tracked-applications/{id}/status` | Move it, with an optional note. |
| `GET /api/tracked-applications/by-job/{job_posting_id}` | Every application sent to one posting. |

A refused transition is a **409** — well-formed, but the lifecycle does not
allow it. An unknown status name, or `draft`, is a **422**. An application that
does not exist *or* belongs to another candidate is a **404** in both cases:
distinguishing them would confirm that someone else's application exists under a
guessed id. The status route returns the whole application rather than the new
status alone, because one move also changes `current_status_since`, can close
the application (`is_open`), and always appends to the history.

The migration is
`migrations/versions/0020_create_application_status_events.py`.

### Already-applied jobs stop being suggested

The tracker feeds back into matching, so a role the candidate has applied to
is not offered to them again. `RankMatchedJobPostings` and
`ListEligibleJobPostings` both drop those postings before returning, which is
the whole feature: the matched list is a list of jobs *to apply to*.

- **Matched on canonical identity, not posting id.** `CanonicalJobIdentity` is
  company + title + location, each collapsed by the same `normalize_text` that
  derives Epic 02's dedup keys. Posting ids would not work: the role
  reappears in the active job set under a new id every time it is re-ingested,
  relisted by the employer, or picked up from a second aggregator, and each of
  those would come back as a job to apply to.
- **`source` is deliberately dropped.** Epic 02's dedup key is *per source* —
  the same opening from Adzuna and from Greenhouse is legitimately two rows,
  because that key answers "did this feed already give me this listing?" This
  identity answers "is this the role I applied to?", and applying through one
  board reaches the employer no matter which feed surfaced it.
- **Not fuzzy, for the same reason Epic 02 is not.** "Backend Engineer" and
  "Backend Engineer II" stay distinct, and a posting naming no location is not
  assumed to be the one applied to in Berlin. Suppression *removes* things from
  the candidate's view, so it has to fail toward showing one job too many
  rather than hiding one they never applied to.
- **Location is snapshotted onto the tracked row** (`job_location`, migration
  `0019`), like `company_name` and `role_title` before it. A join through
  `job_posting_id` would lose the answer in exactly the cases suppression
  exists for — the posting pruned, relisted, or re-ingested. Rows predating the
  column read as `NULL` and are not backfilled: the honest value is "unknown",
  and guessing it from today's posting would assert something about send time
  that nobody knows.
- **Outcome does not matter.** A rejected or withdrawn application still
  suppresses. A rejection is the strongest possible reason not to suggest
  applying again, and re-applying deliberately is something the candidate does
  from the tracker, not something the matcher proposes.
- **Suppressed, or flagged on request.** `GET /api/job-postings/matches`
  excludes them by default; `?include_already_applied=true` returns them with
  `already_applied: true` on the entry, for a client that wants to show a "you
  already applied" section. The flag is set the same way in both modes, so the
  two cannot disagree. The check runs before rationale generation, so a
  suppressed job also costs no LLM call.
- **Read completely, once per run.** `TrackedApplicationRepository.list_applied_identities`
  returns the candidate's distinct roles — three short columns, no limit. A
  limit would quietly un-suppress the oldest applications, and a feature that
  starts nudging again after the hundredth application is worse than none,
  because it looks like it works.

`tests/application/test_applied_job_suppression.py` is the cross-epic check:
it drives the **real** `IngestAggregatorJobs` and the **real**
`SubmittedApplicationLog` rather than hand-building their rows, so the
identity rule is verified against the dedup key it has to agree with — 
including the case where Epic 02 keeps two rows (same role, two sources) and
matching suppresses both anyway.

### What each row says about the documents that went out

Every tracker read — the feed, one application, one posting's applications, and
the response to a status change — carries the exact resume and cover letter the
employer received, resolved from the ids frozen onto the row at send time.

- **Resolved by id, never by "the newest document for this job".**
  `SentDocumentResolver` can look a snapshot up by id and do nothing else. It
  deliberately cannot call `get_latest`, which is the right question at *send*
  time (it is what `SubmittedApplicationLog` asks) and the wrong one
  afterwards: a candidate who revises their resume has a newer version stored
  against the same job, and reading it here would make the tracker restate
  history — showing a document the employer never received, with nothing to
  indicate anything had changed.
- **Carried twice, by id and resolved.** `resume_document_id` /
  `cover_letter_document_id` are always present and are what a caller fetches
  with; `resume` / `cover_letter` are those same references already resolved to
  version, digest, and date, so a thirty-row feed does not cost sixty extra
  requests to label.
- **Never the text.** The same line `ApplicationDocumentSummaryOutput` draws: a
  list view never displays a resume, the text is the most PII-dense content in
  the system, and a caller that wants it asks for one document by id.
  `content_sha256` is what keeps the reference checkable without shipping it.
- **A reference that no longer resolves is reported, not raised.** The write
  path refuses to create one and `ON DELETE RESTRICT` refuses to break one, so
  a null here means something has gone wrong beneath both. The row still comes
  back, with an empty reference and an ERROR log naming the ids: one unreadable
  row must not hide the candidate's whole history, and *that they applied* is
  the fact suppression depends on.
- **One read per distinct document.** A candidate who re-applied to a role has
  several rows pointing at the same snapshots, so the resolver caches within a
  request — and only within one, so nothing can serve a stale snapshot.
- **Nothing on these paths can write a document.** No archive and no generator
  is wired into any of the four use cases; the only thing they hold besides the
  tracker store is a resolver that reads by id.

Alongside that, `allowed_next_statuses` on every row is
`ApplicationStatus.allowed_transitions` passed straight through, so a status
control offers exactly the moves the PATCH will accept. A control that computed
its own would eventually offer one `change_status` refuses, and the candidate
would meet the refusal only after choosing. An empty list means the application
has settled.

`frontend/src/components/ApplicationTracker.tsx` renders all of it — the sent
documents by version and digest, the status control bound to
`allowed_next_statuses`, and the history behind a disclosure once an
application has moved.

### Acceptance check

`docs/epic-06-acceptance-check.md` is Epic 06's Definition of Done, and
`tests/acceptance/test_epic06_tracker_pipeline.py` proves it against a real
database and the real HTTP app: a submission is logged with the exact
documents that went out (checked by *following* the references back to the
archived bytes, and against a newer revision archived afterwards that must not
appear), the status is driven through its lifecycle — recording each move in
the history, refusing the ones the lifecycle forbids — and re-read from the
route the UI renders from, and the applied-to role leaves the matched list and
stays gone after the application is rejected.

---

## Browser automation harness (Epic 05)

The base layer every autofill capability sits on: put a real browser on a
posting's `apply_url` (the one Epic 02 resolved), read what the form is
asking, and write values back. `BrowserAutomationPort` /
`BrowserSessionPort` define it; `PlaywrightBrowserAutomation` drives a
headless Chromium behind them, and nothing above infrastructure ever sees a
browser, page, or selector.

```python
harness = PlaywrightBrowserAutomation(settings)     # wired in the composition root
try:
    async with await harness.open(posting.apply_url) as session:
        for field in await session.read_fields():
            ...                                      # decide a value per field
        await session.fill(handle, "Ada Lovelace")
        await session.attach_file(resume_handle, filename="resume.pdf", content=pdf)
        review_image = await session.screenshot()
finally:
    await harness.shutdown()
```

**Fields are addressed by opaque handles, never selectors.** `read_fields()`
mints a handle per field it discovered and hands back a `FormField` (kind,
label, `required`, options, `maxlength`, current value). A caller can only
touch fields the harness chose to expose, which is what keeps the surface
controlled:

- Hidden, disabled, read-only, invisible, and button controls are never
  discovered — **no field handle can press anything.** Submitting is a
  separate capability with its own handle namespace (below).
- A caller cannot pass a raw CSS/XPath expression, so it cannot reach an
  element that wasn't offered, and cannot smuggle a selector engine
  expression in where a field name is expected.
- Every write re-derives the element's signature and compares it against
  the snapshot first. A handle from an older snapshot, or one whose page
  shifted underneath it, raises `StaleFormFieldError` instead of writing
  into whatever field drifted into that position — the silent, unrecoverable
  failure mode on a real application, seen only by a human reviewer at the
  company.

**Values are matched exactly or refused.** A select accepts an option named
by its exact label or submitted value (normalized for case/whitespace, never
fuzzy); a checkbox/radio accepts a yes/no form or its own label. Anything
else raises `RejectedFieldValueError` carrying the values that *would* have
worked, so a caller can choose again. Picking the nearest option would
submit an answer the candidate never gave.

**Sessions are isolated and always cleaned up.** One harness owns one
browser; each session owns its own `BrowserContext`, so cookies and logins
never cross between applications. Sessions are async context managers,
`close()` is idempotent, and `shutdown()` is the backstop that closes
anything still open plus the browser itself — a browser process outliving
its owner is what takes a worker down. A navigation that fails cleans up
before the exception leaves `open()`.

**Two more reads, and one write that sends.** `read_page_signals()` reports
what else is on the page — frame and script URLs, markup tokens, visible text
— *uninterpreted*: which of those amount to a CAPTCHA is a domain rule
(below), and no implementation of this port contains one. `read_submit_controls()`
/ `press_submit()` are the only way anything is sent, and they are deliberately
unreachable from the filling path: submit handles live in their own snapshot,
so a `FormField` handle passed to `press_submit()` is refused and vice versa,
and pressing requires a caller to have asked for submit controls by name and
chosen one. Only controls that genuinely submit are returned — a "Save draft"
or "Add another employer" button never is. The harness still decides nothing
about *whether* to press; that gate lives in the use case (below).

**Failures are typed, not generic.** `BrowserNavigationError` (timeout, DNS
or connection failure, error status — retried once for 5xx/429/timeouts,
never for other 4xx), `StaleFormFieldError` (re-read the form),
`FormFieldNotFillableError` (wrong operation for the kind, or the element
refused input), `RejectedFieldValueError` (pick a different value),
`SubmitControlNotPressableError` (nothing was sent — safe to retry),
`BrowserSessionClosedError`. No `playwright.*` type escapes infrastructure.

Frames are included — ATS forms are routinely embedded in an iframe.
Custom widgets are not: platforms that hide the native `<select>` and paint
their own combobox leave nothing Playwright would interact with, so
supporting them is its own capability rather than a special case inside
field discovery.

Requires the Chromium build Playwright expects (`playwright install
chromium`, included in `make install`); the harness says so explicitly
rather than failing with a driver error. Timeouts, viewport, retries and
launch flags are all in `Settings` (`BROWSER_*`).

**Two things a session will not do.** `read_page_signals()` reads what kind of
page it is on before anything is touched, and any field the domain marks as
human-only is refused (`HumanOnlyFieldError`) — see "Hard stops & human
hand-off" below.

**Not yet in the container images.** The `Dockerfile` installs the
Playwright wheel with the rest of `requirements.txt` but not the browser
itself. The flow is wired into the API (`/api/job-postings/{id}/autofill` and
the review routes below), so the image that serves it needs
`playwright install --with-deps chromium` and
`BROWSER_LAUNCH_ARGS=["--no-sandbox"]`, since a container generally cannot use
Chromium's sandbox. There is deliberately no Celery task: a background job
cannot review a form, and every route in this flow is one a candidate hits.

---

## Field mapping & autofill (Greenhouse, Lever, Ashby)

What turns "a browser can read this form" into "these are the candidate's
answers". Given a posting whose `apply_url` is on one of the three supported
platforms, `AutofillApplicationForm` reads the form once, fills every
standard field it can from the profile and the stored documents, and reports
back every field it did not fill and why.

```python
output = await AutofillApplicationForm(
    job_posting_repository, profile_repository, document_repository,
    browser, pdf_renderer, review_sessions,
).execute(AutofillApplicationFormInput(user_id=..., job_posting_id=...))

len(output.applied_fields)             # what it filled
output.fields_needing_review           # what it refused to guess at, with reasons
output.unanswered_required_fields      # ...of those, what will block submission
output.screenshot_png                  # proof of the filled form
output.boundaries                      # what only the candidate can do (below)
output.review_session_id               # the parked form they will submit through
```

A field only the candidate may fill — a password, a signature line, a challenge
answer — is surfaced, never planned as a write, so the harness's own refusal is
never reached mid-pass (see "Hard stops & human hand-off" below, and
`HumanOnlyFieldPolicy` for what counts).

### Three pieces, deliberately separate

| Piece | Layer | Answers |
| --- | --- | --- |
| `recognize_application_field` | domain | "What is this field *asking*?" → an `ApplicationFieldSlot`, or None |
| `resolve_profile_field` | domain | "What does the candidate's record say about that?" → a value, or None |
| `AtsFormFieldPlanner` | application | "So what do we do with this widget?" → fill / attach / surface |

The first two are pure functions over markup and over a profile, with no
browser and no database anywhere near them — which is why the mapping rules
can be exercised against a literal form field and reviewed without running
anything. The planner is the only piece that knows both, and it does no I/O
either; the use case is the only piece that touches a browser.

A **slot** is a question, not a widget and not a profile column. "Give us your
family name" is one slot whether the portal calls it `last_name`,
`job_application[last_name]`, or a React input labelled "Surname ✱" — and the
resume slot is one slot whether the form takes an upload or a textarea.

### Recognition, in descending order of trust

1. **The control's own `name`/`id`** — `job_application[first_name]`,
   `urls[LinkedIn]`, `_systemfield_email`. The portal stating what the field
   is. Nested names are read with their nesting, because
   `job_application[educations][][end_date]` is an education date while a bare
   `end_date` could be anything.
2. **`autocomplete`** — a standardized vocabulary the portal opted into.
   Rarer than prose, and more reliable than it.
3. **The label** — ordered phrase rules over whole words. Most of the real
   coverage, and all of Ashby's, since its custom fields carry generated ids.

Exact-or-nothing at every level: no scoring, no edit distance, no
nearest-slot fallback. The two failure modes are wildly asymmetric — an
unrecognized field costs a human a moment's attention, while a
*misrecognized* one writes a wrong answer into a real application under the
candidate's name, seen only by a recruiter at the company.

A label containing "?" is treated as a screening question the company wrote,
and can only match the never-autofilled slots. Without that guard, "Do you
have a GitHub account?" (a yes/no) receives a URL.

### Unmapped fields are surfaced, not guessed

Every field the form presented comes back in `output.fields`, in page order,
whether it was filled or not — a field quietly dropped from the report is the
same failure as one filled with a guess, just harder to notice. The reasons a
field is surfaced are genuinely different situations for whoever reviews it:

- `unrecognized` — the company wrote this question. Expected on much of a
  real form, and not a defect.
- `no_profile_data` — ApplyFlow knows the field; the profile is silent.
  Actionable: filling it in fixes every future application.
- `requires_candidate_answer` — EEO self-ID, which is never autofilled. Not a
  profile gap and not something filling one in would fix.
- `sensitive_data_not_attested` — a legal answer is on file but the candidate
  didn't state it themselves. Confirming it on the profile is the fix.
- `sensitive_answer_not_derivable` — the record doesn't settle this legal
  question exactly, and approximating is the one thing it must not do.
- `requires_candidate_signature` — this field is where the candidate signs.
  Never filled, whatever its label says (see "Hard boundaries" below).
- `unsupported_field_kind` — the data doesn't fit the widget, which usually
  means the field was read wrongly. Plus `document_not_generated` and
  `value_too_long`, which only surface while executing.

### Sensitive fields: two categories, opposite rules

The always-asked questions get their own domain service
(`decide_sensitive_field`) and never touch the ordinary profile resolver —
which refuses them too, so the policy holds even if that routing is later
changed by someone who hasn't read it. `SENSITIVE_SLOTS` classifies each one:

| Category | Slots | Rule |
| --- | --- | --- |
| `legal_attestation` | work authorization, sponsorship, citizenship country, visa type | **Must** be answered when the record answers it exactly |
| `voluntary_self_id` | EEO (gender, race/ethnicity, veteran, disability) | **Never** answered, under any circumstances |

The asymmetry is the whole design. For EEO, silence is safe and an answer is
not. For work authorization it is the reverse: leaving a required
authorization question blank stalls the application, so declining to answer
is not a safe default — what's unsafe is answering *approximately*.

**EEO is never autofilled, even with every category on file.** Disclosure is
voluntary by law and is a decision made **per application** — the same person
may reasonably answer for one employer and decline for the next. An autofill
carrying last week's answer forward would quietly convert one disclosure into
a standing one, and the candidate would never see it happen. An explicit
"decline to self-identify" is itself such a decision, so that isn't submitted
for them either.

**Work authorization is answered exactly, through three gates.** No record →
no answer. Not candidate-attested → no answer. Doesn't settle *this* question
→ no answer, with a reason:

- `PARSED_RESUME` provenance is refused outright
  (`WorkAuthorization.ATTESTING_SOURCES`). Every other profile fact is fine to
  read out of a resume — a slightly-wrong job title is cosmetic. A work
  authorization status is a legal declaration the candidate signs their name
  to, and one inferred from prose is a claim they never made.
- "Are you authorized to work?" comes from the status alone. A visa holder is
  authorized *today*, so yes; needing a sponsor is what "not authorized as
  things stand" means, so no; `OTHER` settles nothing and is refused.
- "Will you now or in the future require sponsorship?" prefers the
  candidate's own explicit answer, and only falls back to the statuses that
  settle it alone. `VISA_HOLDER` is deliberately refused here — a visa can
  expire, need transferring, or need extending, so a current visa says nothing
  reliable about the future.

Answers are the literal strings "Yes"/"No", which is how all three platforms
label these options. A portal writing "Yes, I am authorized to work in the US"
instead gets the value refused and the real options handed back — selecting
the option that merely *starts* with the right word is how a candidate ends up
declaring something they never said.

**Known limitation — jurisdiction.** These questions almost always name a
country, and `WorkAuthorization` doesn't record which jurisdiction its status
refers to, so the answers read the record as the candidate's answer to the
standard application question. Guarding on `citizenship_country` was
considered and rejected: it would falsely refuse every visa holder, whose
citizenship country is by definition not where they're authorized, and
blanking a correct "Yes" is its own harm. Fixing it properly means recording
the jurisdiction on `WorkAuthorization` (an Epic 01 data-model change). Until
then the safeguard is the review step below.

### Flagging sensitive fields in the review step

Every field in the report carries `is_sensitive`, `sensitivity`, and
`requires_confirmation`, so a review UI never infers sensitivity by
pattern-matching slot names — an inference that, gone wrong, renders a visa
declaration as an ordinary text box. On `PlannedField` these are *derived*
properties of the slot rather than fields someone has to remember to set, so a
sensitive field cannot be constructed and reported as ordinary.

Two lists are what a review screen needs:

```python
output.sensitive_fields             # everything to flag, filled or not
output.fields_awaiting_confirmation # filled legal answers, pending approval
```

Both categories belong in the first list: an autofilled work-authorization
answer needs confirming, and an untouched EEO question needs the candidate to
decide. A UI highlighting only one would hide half the sensitive surface.
`requires_confirmation` is the pre-submission gate — true only for a sensitive
value that actually reached the form, since a field the portal refused is
already surfaced for the candidate and doesn't need a second gate pointing at
it.

### Scope is enforced, not documented

`AtsProvider` has exactly three members, and `recognize_application_field`
requires one — so there is no value a caller could pass to ask about a form
the rules were never written for. An apply URL is resolved to a provider by
`identify_ats_board`'s allowlist first, and anything else raises
`UnsupportedAtsFormError` **before a browser is opened**.

**Workday and the other dynamic platforms are out of scope on purpose.**
They are a different problem, not a longer version of this one: they render
in stages, re-mount controls between steps, and expose almost nothing stable
to key on. Pointing these rules at one would not fail — it would confidently
fill the wrong fields.

### Values, documents, and what gets flagged

Values are read verbatim where the profile stores them directly. Two are
*derived* and come back flagged `is_derived`, so a review step can send
attention exactly where the record was interpreted rather than read:

- **First/last name**, split out of the single stored `full_name`. The last
  whitespace-separated token is taken as the family name, which is right for
  the common cases and wrong for others (Spanish and Portuguese names carry
  two surnames). Every alternative is worse — refusing to split leaves
  first/last name blank on nearly every form, and asking a model to guess
  puts a fabricated legal name on a legal document — so it splits, flags, and
  shows the candidate before anything is submitted.
- **Location**, composed from the address when no explicit location is set.

The resume and cover letter come from the stored `ApplicationDocument`
snapshot for that job (the exact text that was produced, never a fresh
generation), rendered to PDF for an upload field or pasted as text into a
textarea — the form picks, and only the shape a field actually takes is
produced, so a paste box never triggers a PDF render. A value longer than the
portal's declared `maxlength` is surfaced rather than truncated: a cover
letter clipped mid-sentence still goes out under the candidate's name.

### Failure is per field, except when it isn't

A form refusing one value (`RejectedFieldValueError`, reported as
`not_accepted` with the values that *would* have worked) or one element
refusing input (`FormFieldNotFillableError`) is recorded against that field
and the rest of the form still fills. Twenty correct fields plus an honest
"the degree dropdown wouldn't take 'B.S.'" is worth far more than an
exception that abandons the form.

`StaleFormFieldError` is the exception and propagates: the page moved
underneath the snapshot, so every remaining handle is suspect and continuing
risks writing into whatever field drifted into position.

**This use case never submits.** It never asks the session for a submit
control, so it holds nothing pressable. What it produces is a filled form, an
honest account of it, and a parked review session; sending is a separate act
in a separate use case (below).

---

## Hard boundaries: where ApplyFlow stops (Epic 05)

Three checks on an application page exist to confirm that the party filling
the form is the person applying, and ApplyFlow treats all three as walls
rather than obstacles: a **login**, a **CAPTCHA**, and a request for the
candidate's **signature**. Getting past any of them is impossible, dishonest,
or both — a login wants a credential ApplyFlow holds none of, a CAPTCHA asks
the one question it cannot answer truthfully, and a signature is the
candidate personally attesting to the application.

`detect_application_boundaries` is a pure function over one page observation
(`PageSignals` — frame and script URLs, markup tokens, visible text, plus the
form's own field labels). The browser layer gathers; the domain decides, so a
new detection rule never means touching the browser adapter.

**The two stops are different, and conflating them would be wrong both ways:**

| Kind | Autofill | Submitting here |
| --- | --- | --- |
| `login` | **stopped** — the page is not the application form, and filling it would type the candidate's details into a sign-in box | no |
| `captcha` | proceeds — the form around the challenge is real, and filling it is most of the value | no |
| `signature` | proceeds, except the signature field itself | no |

Every boundary carries `evidence` (what was seen, so the hand-off is
checkable) and an `instruction` (what the candidate does next, in their
terms). A hand-off is a *result*, not an error: the autofill route answers
`200` with `requires_handoff` set, not a 4xx.

**The signature case is enforced twice, from one vocabulary.** The usual shape
of a signature on an ATS form is a text input labelled "Signature (type your
full name)" — a label the field recognizer reads as a request for the
candidate's name, which it can answer. So `is_signature_field` makes the
planner refuse that field before recognition runs (`requires_candidate_signature`),
*and* the page-level rule blocks submission. A hand-off that refused to submit
after signing for the candidate would be worse than no hand-off at all.

**Detection is deliberately narrow on prose.** A false negative costs a
candidate a stalled application they can see; a false positive costs them the
whole autofill on a form that was fine, and teaches them to ignore the one
message in this flow that must be believed. So the text rules only match
instructions to a person ("draw your signature", "verify you are human") and
never descriptive prose — notably not the boilerplate "constitutes an
electronic signature" paragraph that appears on a large share of ordinary ATS
forms. Markup tokens are matched whole, so `captcha-free-hiring` in a class
name is not a challenge, and the login path rule reads the URL's path only, so
a `?redirect_to=/login` query parameter is not a wall.

---

## Review and submit (Epic 05)

A filled form is reviewed by a person and then sent by that person. Between
those two things is a live browser page, so `ApplicationReviewSessions` keeps
the filled form parked while the candidate reads it — otherwise submitting
would mean re-opening the portal and filling a real application a second time.

```
POST   /api/job-postings/{id}/autofill              fill the form, park it
POST   /api/autofill-sessions/{id}/fields/{field_id} answer what was surfaced
POST   /api/autofill-sessions/{id}/submit           send it
DELETE /api/autofill-sessions/{id}                  walk away
```

**Answering a surfaced field** writes the candidate's own value onto the same
live page and returns the whole updated report, since an answer can clear the
last thing standing between the application and the Submit button. It is also
the only path by which an EEO answer ever reaches a form. A value the
candidate typed is already their statement, so it comes back
`answered_by_candidate` and needs no confirmation.

**Submitting** is refused unless all four of these hold, each re-checked
against the live page rather than against a report the client may have been
holding for ten minutes:

1. a candidate asked for it — the instruction is an input, and nothing
   scheduled, queued, or chained from the autofill pass can produce one;
2. no boundary is on the page — so a CAPTCHA that appeared *after* the form
   was filled stops the submission instead of being submitted past;
3. every sensitive value ApplyFlow filled has been confirmed
   (`confirmed_field_ids`, a required input rather than a defaulted flag);
4. every required field is answered — refused here rather than sent for the
   portal to reject, because a rejected submission on several portals comes
   back with the uploads dropped.

Which button gets pressed is never guessed: one control means that one, several
means the candidate names it ("Submit application" and "Submit and create an
account" are both submissions), none means this portal submits from script the
harness cannot see and the answer is a hand-off.

Afterwards the receipt claims only what is known. `is_confirmed_sent` is the
field to trust, not the `200`: the press succeeded either way, and only the
absence of a post-press boundary means the portal took the application.

**Reviews are process-local and time-bounded.** Each holds a browser context,
so they expire (`AUTOFILL_REVIEW_TTL_SECONDS`), are capped
(`AUTOFILL_MAX_PARKED_REVIEWS`), and are closed on shutdown. One review per
candidate-and-job: a second pass replaces the first. An API served by several
workers needs sticky routing for these routes — a request that lands elsewhere
gets the same honest "run the autofill again" an expired review gets.

**The acceptance check.** `docs/epic-05-acceptance-check.md` is Epic 05's
Definition of Done, and `tests/acceptance/test_epic05_autofill_pipeline.py`
proves it: a real Chromium fills a real Greenhouse-shaped form, hands off at a
login wall, a CAPTCHA and a signature request, and a candidate submits — with
the receiving server's record of the POST checked field by field, down to an
EEO answer that is *empty* even though the profile has one on file.

---

## Hard stops & human hand-off

**ApplyFlow never solves CAPTCHAs, never creates accounts, and never types
passwords or signatures.** Not "not yet" — each of those is a step where the
act itself is the point: a CAPTCHA exists to establish that a human is
present, a signature is a legal attestation by a named person, a credential is
that person's identity. Software doing any of them is not automating a chore,
it is impersonating the candidate. So automation stops and the candidate takes
over.

Three boundaries are modeled (`HardStopKind`), and the enum is closed:
`CAPTCHA`, `ELECTRONIC_SIGNATURE`, `ACCOUNT_WALL`. Portal quirks that merely
need work (custom combobox widgets, multi-page wizards) are missing
capabilities, not boundaries, and are not modeled here at all.

### Detected on two levels, because they fail differently

**Page level**, before anything is touched. `read_page_signals()` reduces the
live page — main document *and* frames — to a `PortalPageSignals` reading:
the landed URL, the visible text, the scripts and iframes it loads, the markup
names of anything that can host a widget, its field labels, and how many
password fields it presents. `HardStopDetector` (pure domain, rules not a
model — a portal's own text is untrusted input, and a safety gate has to be
deterministic and auditable) reads that and returns a `HardStop` per boundary
found, each carrying the evidence for saying so.

**Field level**, on every single write. `HumanOnlyFieldPolicy` tags each
discovered field with `human_only_boundary`, and `fill`/`attach_file` refuse a
tagged one outright (`HumanOnlyFieldError`). That is what makes the guarantee a
property of the system rather than a promise about its callers: the refusal
lives in the layer that actually types, so no use case — and no model driving
one — can route around it. It also catches what the page check cannot: a
signature block revealed on page two of a wizard, a session that expires
mid-fill, and a credential box masked as `type="text"` (recognized from its
name and `autocomplete` hint).

Both levels read one shared vocabulary (`hard_stop_vocabulary`), so they cannot
drift into disagreeing about what a boundary is. The lists lean toward
stopping, deliberately: a false hand-off costs one look at a page the candidate
was going to see anyway, a missed one costs the thing this whole module
prevents. What is *not* a boundary: an "I certify the above is true" checkbox,
an "I agree" checkbox, a "Sign in" link in a page header. Those are ordinary
ATS furniture, and handing off on them would fire so often candidates would
learn to click past hand-offs without reading them.

### The pause withholds the form

`InspectApplicationPortal` is the gate every autofill capability sits behind:

```python
output = await inspect_application_portal.execute(
    InspectApplicationPortalInput(user_id=user.subject, job_posting_id=posting.id)
)
if output.is_handed_off:
    output.handoff          # what was hit, where, why, and what the user must do
    output.fields           # always empty — there is nothing to fill
else:
    output.fields           # the questions the portal asks
```

It reads signals first and only reads the form if nothing was found. A flow
that read the fields and *then* decided would already be holding a path to a
login page's password box; withholding them means a paused portal cannot be
filled by accident, by anyone. Handing off is a normal `200`, not an error —
nothing failed, ApplyFlow did exactly what it should.

### Hand-off state is clear and resumable

A hand-off is stored (`PortalHandoff`, `portal_handoffs`), because a pause that
only exists in one response is not resumable: the candidate leaves to do the
step in another tab and has to be able to come back to it. It records the
posting, the apply URL, **the URL automation actually stopped on** (often a
redirect target — that is where the candidate should go), every boundary with
its evidence, and its own lifecycle:

```
AWAITING_USER ──► RESUMED     "I did the step — continue"
              └─► ABANDONED   "I'm finishing this one myself"
```

- **At most one open hand-off per candidate and posting**, enforced by a
  partial unique index. Re-inspecting a portal the candidate has not dealt with
  yet refreshes that one hand-off (new evidence, new paused URL, same id) rather
  than stacking near-duplicates.
- **Resuming records an assertion, not a verification.** The candidate solves
  the CAPTCHA in *their* browser; ApplyFlow's next session shares none of that
  state, so a "verified" resume would be either impossible to satisfy or a lie.
  The next inspection re-reads the portal and raises a *fresh* hand-off if the
  boundary is still there.
- **Abandoning is a real ending.** A portal that requires an account will
  require one next time too; without this, hand-offs with no possible resolution
  would pile up forever.
- **The one case ApplyFlow closes a hand-off itself**: an inspection that finds
  no boundary while one is open. The wall is gone, which is stronger evidence
  than anyone's word, so it resolves with a note saying exactly that and reports
  the id in `cleared_handoff_id`.
- Resolving twice is a `409` (`HandoffStatus` refuses the second transition), so
  a double-clicked "continue" is a rejected request rather than a rewritten
  record. Someone else's hand-off is a `404`, never a `403`, which would confirm
  the id exists.

Evidence lines describe the *portal's* page and carry nothing about the
candidate, so they are safe to log and display. The resolution note is the
candidate's own free text and is treated as sensitive: flagged on the column,
returned only to its owner, never logged.

---

## Review & submit (the user is the submitter)

**Nothing is ever submitted unattended.** ApplyFlow prepares an application and
then stops: the candidate reads it, changes whatever they like, decides every
sensitive field, and presses submit themselves. That is the whole point of the
flow, so the gates are in the domain rather than in the UI — a client that
ignores them gets the same refusal the button would have shown.

```
POST /api/job-postings/{id}/review          fill the form, open a review
GET  /api/job-postings/{id}/review          the review in progress
POST /api/application-reviews/{id}/answers/{field_key}   set | confirm | decline
POST /api/application-reviews/{id}/submit   the candidate submits
```

### Opening a review is three steps, in this order

1. **Check the portal** (`InspectApplicationPortal`) — read it before touching
   it. A hard boundary means the response is the hand-off, `review` is null, and
   **nothing was filled**.
2. **Fill it** (`AutofillApplicationForm`) — every standard field from the
   profile and the stored documents, plus a screenshot of the result.
3. **Open the review** (`OpenApplicationReview`) — turn that report into
   `ApplicationReview`: every question in page order, editable, with the
   sensitive ones awaiting a decision.

The interface layer sequences those three; every rule lives inward. Step 3
re-checks the hand-off gate itself, so skipping step 1 could not produce a
review on a walled portal — step 1 exists to avoid filling a form nobody could
have submitted, not to be the gate.

### What the candidate sees, and can change

`answers` is every field the form presented, in the portal's order, whether it
was filled or not — a review that showed only the problems would have people
approving an application they never read. Each answer carries:

- **`origin`** — `autofilled`, `candidate`, `declined`, or `unanswered`. Who is
  responsible for this answer is a different claim from what the answer is, and
  the review says both.
- **`explanation`** — why ApplyFlow left it, in words that can be acted on
  ("your profile does not answer this yet", "ApplyFlow never answers this one").
  A value the portal *refused* is not shown as the answer: the field stays
  unanswered and the explanation says what was tried and what the form accepts.
- **`sensitivity`** / **`needs_decision`** — see below.

Any field can be edited, including the ones ApplyFlow filled, and an edit
records the candidate as its author. Emptying a field is stored as a *decline*
rather than as a blank of unknown intent.

### Sensitive fields cannot be passed over

Every sensitive field — the four legal attestations and EEO self-identification
— starts `needs_decision: true`, and only the candidate's own action clears it:
**confirm** the answer as it stands, **change** it, or **decline** it. There is
no bulk approve, and nothing else in the system settles one. Declining is always
offered, because a gate with one way through is not consent.

That gate is enforced in `ApplicationReview.record_submission`, which refuses
while any `SubmissionBlocker` stands:

- `PENDING_SENSITIVE_DECISION` — a sensitive field the candidate has not settled.
- `OPEN_HARD_STOP` — an unresolved hand-off on this portal; handing someone an
  application to send through a portal that is still walled is a dead end.

A required field with no answer is deliberately **not** a blocker. The
`required` flag is only as trustworthy as the portal's markup (the browser port
treats `False` as "not asserted"), so it is surfaced as a prominent warning and
the candidate decides — being locked out of recording your own submission by a
signal ApplyFlow may have misread is worse than sending an incomplete form.

### Submitting

`can_submit` is the single flag the button binds to, and the submit route
re-computes the same blockers against the hand-off state *as of now* — so a wall
raised while the candidate was reading is caught, and a client that posts anyway
is refused (409, naming what is missing). Submitting twice is a 409 too.

Once submitted, the answers are frozen: they are the record of what the
candidate sent, for the same reason `ApplicationDocument` snapshots are
write-once. Re-filling a posting opens a *new* review and supersedes any draft;
a submitted one is never touched.

**ApplyFlow does not press the portal's submit button.** It cannot — the harness
discovers no buttons, so there is nothing there to press — and the API never
implies it did: the status is `submitted_by_user`, and the submit response
carries `apply_url`, which is where the candidate goes to complete the send with
their approved answers in front of them. Handing a live filled browser session
to a human to finish in place is a separate capability and is not built.

SENSITIVE: a review's answers are what goes onto a real application (name,
email, address, work-authorization declarations) and the submission note is the
candidate's free text. Both are flagged on `application_reviews`, returned only
to their owner, and never logged — log the review id, the posting id, and counts.

---

## Getting Started

### Option A — Docker (recommended)

```bash
cp .env.example .env          # then set OPENAI_API_KEY
docker compose up --build
```

Services:
- API: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:5173
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

Apply migrations (first run):

```bash
docker compose exec api alembic upgrade head
```

### Option B — Local development

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium   # browser used by the portal automation harness
cp .env.example .env          # then edit values
# start Postgres + Redis (e.g. via docker compose up db redis)
alembic upgrade head
uvicorn src.interfaces.http.app:app --reload
```

Celery worker (separate terminal):

```bash
celery -A src.infrastructure.tasks.celery_app.celery_app worker --loglevel=info
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## Useful Commands

Run from the repo root (see the `Makefile`):

```bash
make test              # run the pytest suite
make lint              # ruff + mypy
make format            # black + ruff --fix
make migrate           # alembic upgrade head
make up                # docker compose up --build
make frontend-install  # npm install
make frontend-build    # tsc -b && vite build
make frontend-lint     # eslint
make frontend-format   # prettier --write
```

CLI example:

```bash
python -m src.interfaces.cli.main create \
  --email dev@example.com --company Acme --role Engineer \
  --description "Build great things"
```

---

## API Overview

All `/api/applications*` and `/api/resumes*` routes require
`Authorization: Bearer <supabase-jwt>`.

| Method | Path                                | Description                          | Auth required |
| ------ | ----------------------------------- | ------------------------------------ | ------------- |
| GET    | `/health`                           | Health check                         | No            |
| POST   | `/api/applications`                 | Create a job application             | Yes           |
| GET    | `/api/applications?candidate_email=`| List a candidate's ranked applications | Yes         |
| POST   | `/api/applications/{id}/analyze`    | AI resume/JD analysis + cover letter | Yes           |
| POST   | `/api/applications/{id}/submit`     | Move DRAFT → APPLIED                 | Yes           |
| POST   | `/api/resumes`                      | Upload a resume (PDF/DOCX/text); stores it and returns extracted text | Yes |
| GET    | `/api/resumes/{id}`                 | Fetch one resume's metadata + extracted text | Yes   |
| GET    | `/api/resumes`                      | List the current user's uploaded resumes | Yes       |
| GET    | `/api/job-postings/matches?limit=&include_already_applied=` | Ranked, filtered, scored job matches for the current user; roles already applied to are excluded unless `include_already_applied=true`, which returns them flagged | Yes |
| POST   | `/api/job-postings/{id}/feedback`   | Submit thumbs-up/down feedback on a match | Yes      |
| GET    | `/api/job-postings/feedback`        | List the current user's feedback history | Yes       |
| GET    | `/api/job-postings/feedback/analysis` | Bucketed feedback agreement-rate summary (tuning signal) | Yes |
| GET    | `/api/job-postings/{id}/gaps`       | Requirements this candidate's record doesn't yet back | Yes |
| POST   | `/api/gap-resolution/questions`     | One neutral question per gap, minus the ones already answered | Yes |
| POST   | `/api/gap-resolution/answers`       | Capture an answer to a gap question (a decline stores nothing) | Yes |
| POST   | `/api/job-postings/{id}/tailored-resume` | Generate a provenance-guarded tailored resume; stores the exact text sent | Yes |
| POST   | `/api/job-postings/{id}/cover-letter` | Generate a provenance-guarded cover letter; stores the exact text sent | Yes |
| POST   | `/api/job-postings/{id}/documents/{kind}/revisions` | Store the candidate's edited document as the next version; re-guarded first | Yes |
| GET    | `/api/job-postings/{id}/documents`  | List every document stored for one job (both kinds, all versions) | Yes |
| GET    | `/api/job-postings/{id}/documents/{kind}/latest` | The resume/cover letter this application went out with | Yes |
| GET    | `/api/application-documents`        | The current user's stored documents across every job (tracker feed) | Yes |
| GET    | `/api/application-documents/{id}`   | One stored snapshot, with its exact text | Yes |
| POST   | `/api/portal/inspections`           | Read a posting's application portal; returns its questions, or the hand-off that stopped ApplyFlow (still a 200) | Yes |
| GET    | `/api/portal/handoffs?open_only=`   | Hand-offs waiting on the candidate, plus recent resolved ones | Yes |
| POST   | `/api/portal/handoffs/{id}/resume`  | "I did the human-only step" — ApplyFlow may work this portal again | Yes |
| POST   | `/api/portal/handoffs/{id}/abandon` | "I'm finishing this application myself" — ApplyFlow stops waiting | Yes |
| POST   | `/api/job-postings/{id}/review`     | Fill the application form and open a review over it (200 with `review: null` when a hard stop blocked it) | Yes |
| GET    | `/api/job-postings/{id}/review`     | The review in progress for this posting, with the submit gate | Yes |
| POST   | `/api/application-reviews/{id}/answers/{field_key}` | One decision about one field: `set` a value, `confirm` it, or `decline` it | Yes |
| POST   | `/api/application-reviews/{id}/submit` | **The candidate submits.** Refused while any blocker stands; returns the portal URL to finish on | Yes |
| GET    | `/api/tracked-applications`         | The tracker: every application sent, newest first, each with the exact documents that went out. `?status=` (repeatable) or `?open_only=true` | Yes |
| GET    | `/api/tracked-applications/{id}`    | One application with its full status history | Yes |
| GET    | `/api/tracked-applications/by-job/{job_posting_id}` | Every application this candidate sent to one posting | Yes |
| PATCH  | `/api/tracked-applications/{id}/status` | Record what became of one application, with an optional note. 409 for a move the lifecycle forbids, 422 for a value that is not a status (or is `draft`) | Yes |

---

## Testing

Tests mirror the layer structure and use in-memory fakes for ports, proving
the domain and application layers are decoupled from infrastructure:

```
tests/domain/        # entities & value objects (no I/O)
tests/application/   # use cases with fake repos/ports
tests/acceptance/    # per-epic Definition-of-Done flows (opt-in, real infra)
```

```bash
pytest
```

`tests/acceptance/` is the exception to the fakes rule: each file is one
epic's Definition-of-Done flow run against a real database, real API keys,
and the real HTTP app with real auth. Every one is skipped unless its own
`RUN_EPIC**_ACCEPTANCE_TEST=1` is set, so a plain `pytest` never touches a
real database or spends money:

```bash
RUN_EPIC03_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic03_matching_pipeline.py -v -s
RUN_EPIC04_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic04_tailoring_pipeline.py -v -s
RUN_EPIC05_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic05_autofill_pipeline.py -v -s
RUN_EPIC06_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic06_tracker_pipeline.py -v -s
```

See `docs/epic-03-acceptance-check.md`, `docs/epic-04-acceptance-check.md`,
`docs/epic-05-acceptance-check.md`, and `docs/epic-06-acceptance-check.md`
for what each one proves and which env vars it needs. Epic 05's needs no API
keys and spends nothing: it drives a
real Chromium against a local server that records what was submitted to it,
with the portal host mapped to 127.0.0.1 so a real Greenhouse apply URL
resolves there — the one thing that check must never do is send an
application to an actual employer.

`tests/infrastructure/test_playwright_browser_automation.py` is the other
exception: it drives a real headless Chromium against a real local HTTP
server on 127.0.0.1 (no network, no keys, no cost), because page lifecycle
timing and navigation failures are exactly what a fake page object would
not reproduce. It skips itself if `playwright install chromium` hasn't been
run, so a plain `pytest` still passes without it.

---

## Project Structure

```
.
├── src/
│   ├── domain/           # entities, value objects, repo interfaces, domain services
│   ├── application/      # use cases, DTOs, ports, mappers
│   ├── infrastructure/   # DB, LLM, Celery, browser, config (implements interfaces)
│   └── interfaces/       # FastAPI controllers, CLI, composition root
├── frontend/             # React + TypeScript (Vite)
├── migrations/           # Alembic migrations
├── tests/                # layer-mirrored tests
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```
