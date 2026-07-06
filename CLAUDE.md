# Architecture: Clean Architecture

## Layer Map
- `domain/`         → Entities, Value Objects, Domain Services, Repository Interfaces
- `application/`    → Use Cases, DTOs, Application Services
- `infrastructure/` → DB, LLM clients, HTTP clients, MCP servers, external APIs
- `interfaces/`     → Controllers, Route handlers, CLI, Agent entry points

## Dependency Rule (ABSOLUTE)
Dependencies must ONLY point inward:

  interfaces → application → domain
  infrastructure → application → domain

## What this means in practice
- `domain/` imports NOTHING from outside itself
- `application/` imports only from `domain/`
- `infrastructure/` implements interfaces defined in `domain/` or `application/`
- `interfaces/` orchestrates use cases, never contains business logic

## Forbidden patterns
- Never import infrastructure directly into domain or application
- Never put business logic in controllers or route handlers
- Never let a use case know which DB or LLM is being used
- Never use `any` as a shortcut around layer contracts

## Agent behavior
- Before creating a file, identify which layer it belongs to
- If a concept doesn't fit cleanly in one layer, ask before proceeding
- Prefer extending existing abstractions over creating new ones
