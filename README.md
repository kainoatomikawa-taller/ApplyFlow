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
  `UserProfile` (aggregate root — a candidate's contact info plus their
  `WorkHistoryEntry`, `EducationEntry`, and `Skill` child entities — the data
  spine matching, tailoring, and autofill read from); `Resume` (an uploaded
  resume file's metadata + extracted text — enforces the accepted file
  formats and size limit; see "Resume upload & file handling" below)
- `value_objects/` — `ApplicationStatus` (state machine), `EmailAddress`,
  `MatchScore`, `ProficiencyLevel`, `ProvenanceSource` (source tag required
  on every stored fact — see "Provenance tagging" below)
- `repositories/` — `JobApplicationRepository`, `ProfileRepository`,
  `ResumeRepository` **interfaces** (WHAT, not HOW)
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
   each entry carrying its score, rationale, and gap list.
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

- Hidden, disabled, read-only, invisible, and submit controls are never
  discovered — **nothing this harness returns can submit an application.**
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

**Failures are typed, not generic.** `BrowserNavigationError` (timeout, DNS
or connection failure, error status — retried once for 5xx/429/timeouts,
never for other 4xx), `StaleFormFieldError` (re-read the form),
`FormFieldNotFillableError` (wrong operation for the kind, or the element
refused input), `RejectedFieldValueError` (pick a different value),
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

**Not yet in the container images.** The `Dockerfile` installs the
Playwright wheel with the rest of `requirements.txt` but not the browser
itself, since nothing invokes the harness in a container yet — there is no
use case or Celery task on top of it, and it isn't wired into the
composition root. Whoever builds the first autofill capability adds
`playwright install --with-deps chromium` to the image that runs it
(the worker, most likely) and sets `BROWSER_LAUNCH_ARGS=["--no-sandbox"]`,
since a container generally cannot use Chromium's sandbox.

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
| GET    | `/api/job-postings/matches?limit=`  | Ranked, filtered, scored job matches for the current user | Yes |
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
```

See `docs/epic-03-acceptance-check.md` and
`docs/epic-04-acceptance-check.md` for what each one proves and which env
vars it needs.

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
