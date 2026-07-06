# Layer: Domain

## Responsibility
The heart of the application. Contains all business rules and logic.
Zero knowledge of the outside world.

## Allowed
- Entities (classes with identity and lifecycle)
- Value Objects (immutable, equality by value)
- Domain Services (logic that doesn't belong to one entity)
- Repository interfaces (abstractions, NOT implementations)
- Domain Events
- Custom domain exceptions

## Imports allowed
- Other files within `domain/`
- Native language primitives only
- Zero third-party dependencies

## Forbidden
- Any import from `application/`, `infrastructure/`, or `interfaces/`
- ORM decorators or DB annotations
- HTTP types (Request, Response, Headers)
- LLM client calls or AI SDK imports
- `console.log` or logging frameworks
- Environment variables (`process.env`)

## Patterns to follow
- Entities protect their own invariants (validation inside the constructor)
- Repository interfaces describe WHAT, not HOW
- Domain services receive their dependencies via constructor

## Example structure
```
domain/
├── entities/
├── value-objects/
├── repositories/
└── services/
```
