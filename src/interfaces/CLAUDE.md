# Layer: Interfaces (Adapters)

## Responsibility
Entry points into the application. Translates external input into
use case calls, and use case output into external responses.

## Allowed
- HTTP controllers / route handlers
- CLI commands
- Agent entry points and tool handlers
- GraphQL resolvers
- WebSocket handlers
- Input validation (schema validation only, not business rules)
- Response serialization

## Imports allowed
- Anything from `application/` (use cases, DTOs)
- Framework types (Express Request/Response, etc.)

## Forbidden
- Business logic of any kind
- Direct domain entity manipulation
- Direct repository or infrastructure calls (must go through use cases)
- Database queries

## Patterns to follow
- Controllers are thin: validate input → call use case → serialize output
- One controller per resource or domain concept
- Validation happens here, but rules are enforced in domain
- Never return raw domain entities — use DTOs from the use case output

## Agent behavior
- If you're writing more than ~20 lines in a controller, extract to a use case
- Input validation is allowed here; business validation is NOT
- HTTP status codes are decided here based on application exceptions
