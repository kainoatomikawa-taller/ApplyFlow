# Layer: Application

## Responsibility
Orchestrates domain objects to fulfill use cases.
Knows WHAT to do, not HOW (no implementation details).

## Allowed
- Use Cases (one class per use case)
- DTOs (input/output contracts for use cases)
- Application Services (multi-use-case orchestration)
- Port interfaces (abstractions for infrastructure needs)
- Mappers (domain ↔ DTO)

## Imports allowed
- Anything from `domain/`
- Other files within `application/`

## Forbidden
- Direct imports from `infrastructure/` or `interfaces/`
- Any ORM, HTTP client, or LLM SDK import
- Business rule logic (belongs in domain)
- Presentation logic (belongs in interfaces)

## Patterns to follow
- Each use case is a single class with an `execute(dto)` method
- Use cases receive repository and service interfaces via constructor (DI)
- Use cases return DTOs, never domain entities directly
- Never let a use case depend on another use case directly

## Agent behavior
- If you're writing an `if` that checks a business rule → move it to domain
- If you're writing SQL or calling an API → you're in the wrong layer
- New use case = new file, always
