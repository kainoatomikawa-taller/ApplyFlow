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
| Packaging    | Docker, docker-compose                       |

---

## Clean Architecture

This project follows **Clean Architecture**. Source code lives under `src/`
split into four layers. **Dependencies only ever point inward.**

```
interfaces  ──►  application  ──►  domain
infrastructure ─►  application  ──►  domain
```

### `src/domain/` — the core (depends on nothing)
Pure business logic with zero third-party imports.
- `entities/` — `JobApplication` (aggregate root, protects its own invariants)
- `value_objects/` — `ApplicationStatus` (state machine), `EmailAddress`, `MatchScore`
- `repositories/` — `JobApplicationRepository` **interface** (WHAT, not HOW)
- `services/` — `ApplicationRankingService` (pure domain logic)
- `exceptions.py` — domain exceptions

### `src/application/` — use cases (depends only on domain)
Orchestrates the domain to fulfill use cases. No DB, HTTP, or LLM code.
- `use_cases/` — one class per use case, each with an `execute(dto)` method
  (`CreateJobApplication`, `AnalyzeJobApplication`, `SubmitJobApplication`,
  `ListCandidateApplications`, `GetLlmCompletion`)
- `dtos/` — input/output contracts (entities never cross the boundary)
- `ports/` — outbound abstractions (`ResumeAnalyzerPort`, `TaskQueuePort`,
  `IdGeneratorPort`, `AuthVerifierPort`, `LlmClientPort`) implemented by
  infrastructure
- `mappers/` — domain ↔ DTO translation

### `src/infrastructure/` — implementations (depends on domain + application)
All I/O lives here. Implements the interfaces defined further in.
- `persistence/` — SQLAlchemy models + `SqlAlchemyJobApplicationRepository`
  (implements the domain repository interface, maps rows ↔ entities)
- `llm/` — `LangChainResumeAnalyzer` (implements `ResumeAnalyzerPort`) and
  `AnthropicLlmClient` (implements `LlmClientPort` — the app's single LLM
  integration; see below)
- `tasks/` — Celery app, tasks, and `CeleryTaskQueue` (implements `TaskQueuePort`)
- `services/` — `UuidIdGenerator` (implements `IdGeneratorPort`)
- `auth/` — `SupabaseJwtVerifier` (implements `AuthVerifierPort`)
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
- **Model**: defaults to `claude-haiku-4-5-20251001`, configurable via
  `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKENS`.

Try the full path end-to-end with the CLI, which wires
`AnthropicLlmClient` → `GetLlmCompletion` (the generic use case every future
LLM feature can call through):

```bash
python -m src.interfaces.cli.main llm-ping --prompt "Say hello in one word."
```

Unit tests (`tests/infrastructure/test_anthropic_llm_client.py`,
`tests/application/test_get_llm_completion.py`) mock the SDK so `pytest`
never makes a network call or spends money. To prove a real completion
against Anthropic's API, run the opt-in live test with a real key:

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

All `/api/applications*` routes require `Authorization: Bearer <supabase-jwt>`.

| Method | Path                                | Description                          | Auth required |
| ------ | ----------------------------------- | ------------------------------------ | ------------- |
| GET    | `/health`                           | Health check                         | No            |
| POST   | `/api/applications`                 | Create a job application             | Yes           |
| GET    | `/api/applications?candidate_email=`| List a candidate's ranked applications | Yes         |
| POST   | `/api/applications/{id}/analyze`    | AI resume/JD analysis + cover letter | Yes           |
| POST   | `/api/applications/{id}/submit`     | Move DRAFT → APPLIED                 | Yes           |

---

## Testing

Tests mirror the layer structure and use in-memory fakes for ports, proving
the domain and application layers are decoupled from infrastructure:

```
tests/domain/        # entities & value objects (no I/O)
tests/application/   # use cases with fake repos/ports
```

```bash
pytest
```

---

## Project Structure

```
.
├── src/
│   ├── domain/           # entities, value objects, repo interfaces, domain services
│   ├── application/      # use cases, DTOs, ports, mappers
│   ├── infrastructure/   # DB, LLM, Celery, config (implements interfaces)
│   └── interfaces/       # FastAPI controllers, CLI, composition root
├── frontend/             # React + TypeScript (Vite)
├── migrations/           # Alembic migrations
├── tests/                # layer-mirrored tests
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```
