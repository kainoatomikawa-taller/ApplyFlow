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
  `ListCandidateApplications`)
- `dtos/` — input/output contracts (entities never cross the boundary)
- `ports/` — outbound abstractions (`ResumeAnalyzerPort`, `TaskQueuePort`,
  `IdGeneratorPort`) implemented by infrastructure
- `mappers/` — domain ↔ DTO translation

### `src/infrastructure/` — implementations (depends on domain + application)
All I/O lives here. Implements the interfaces defined further in.
- `persistence/` — SQLAlchemy models + `SqlAlchemyJobApplicationRepository`
  (implements the domain repository interface, maps rows ↔ entities)
- `llm/` — `LangChainResumeAnalyzer` (implements `ResumeAnalyzerPort`)
- `tasks/` — Celery app, tasks, and `CeleryTaskQueue` (implements `TaskQueuePort`)
- `services/` — `UuidIdGenerator` (implements `IdGeneratorPort`)
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
make test      # run the pytest suite
make lint      # ruff + mypy
make format    # black + ruff --fix
make migrate   # alembic upgrade head
make up        # docker compose up --build
```

CLI example:

```bash
python -m src.interfaces.cli.main create \
  --email dev@example.com --company Acme --role Engineer \
  --description "Build great things"
```

---

## API Overview

| Method | Path                                | Description                          |
| ------ | ----------------------------------- | ------------------------------------ |
| GET    | `/health`                           | Health check                         |
| POST   | `/api/applications`                 | Create a job application             |
| GET    | `/api/applications?candidate_email=`| List a candidate's ranked applications |
| POST   | `/api/applications/{id}/analyze`    | AI resume/JD analysis + cover letter |
| POST   | `/api/applications/{id}/submit`     | Move DRAFT → APPLIED                 |

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
