# ADR 0001: Application shell — web app vs. CLI-first

## Status

Accepted

## Context

ApplyFlow needs one consistent entry point that every later epic builds on
top of. The two realistic options are:

1. **CLI-first** — a terminal command (`applyflow ...`) as the primary
   surface, with a web UI (if any) added later as a thin wrapper.
2. **Web app** — a browser UI as the primary surface, with the CLI (if any)
   kept as a secondary, internal tool.

The deciding factor is Epic 5: **review-and-submit**. That epic's core loop
is a human looking at an AI-drafted cover letter and a match score sitting
next to the original job description, editing text, and approving or
rejecting — repeatedly, across many applications, while comparing several
fields at once. That is an interface-design problem (layout, side-by-side
comparison, inline editing, visible status) more than a scripting problem.

## Decision

**Web app is the primary shell.** The existing `frontend/` (React 18 +
TypeScript + Vite) is the chosen scaffold, talking to the FastAPI backend
(`src/interfaces/http/`) over its `/api/applications*` routes.

The CLI (`src/interfaces/cli/main.py`) is kept as a **secondary adapter**
for local scripting and quick manual checks (e.g. `llm-ping` to smoke-test
the LLM integration without opening a browser) — not as a candidate
replacement for the review UI.

### Rationale

- **Human review is the central workflow, and it's visual.** Reviewing a
  match score + tailored cover letter next to a job description, then
  editing and approving, needs a layout with multiple panes, inline text
  editing, and visible state — all things a browser does natively and a
  terminal fights against.
- **Long-form text editing.** Cover letters and job descriptions are
  paragraphs of prose. Editing prose in a terminal (even with `$EDITOR`
  shell-outs) is a worse experience than a `<textarea>`.
- **Low technical bar for the end user.** ApplyFlow's candidate-facing
  audience shouldn't need a terminal to track and submit applications.
- **The CLI doesn't disappear.** It stays valuable for the maintainer as a
  fast, scriptable path to the same use cases (already proven by `create`
  and `llm-ping` in `src/interfaces/cli/main.py`) — useful for
  smoke-testing and automation, but not for the review experience itself.
- **Both adapters already share the same use cases.** Per the Clean
  Architecture layering, `frontend/` talks to `src/interfaces/http/`, and
  the CLI talks to the same `application/use_cases/` directly. Neither
  adapter contains business logic, so nothing about this decision is
  locked in at the domain/application level — a second UI (or a richer
  CLI) could be added later without touching either.

## Consequences

- All future epics (including Epic 5's review-and-submit screens) are built
  as views/components under `frontend/src/`, calling the FastAPI routes in
  `src/interfaces/http/controllers/`.
- The CLI is maintained only as far as it stays useful for scripting/dev
  workflows; it is not expected to grow a review UI of its own.
- Both adapters read environment selection from the config layer
  (`src/infrastructure/config.py` on the backend, `VITE_API_URL` /
  `frontend/.env` on the frontend) rather than hardcoding endpoints — see
  `frontend/.env.example`.
