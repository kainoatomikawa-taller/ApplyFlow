# Layer: Infrastructure

## Responsibility
Implements the interfaces defined in domain/application.
All I/O lives here: databases, LLMs, HTTP clients, MCP servers, queues.

## Allowed
- Repository implementations
- ORM models and migrations
- LLM client wrappers (Anthropic SDK, OpenAI, etc.)
- MCP server adapters
- External HTTP clients
- Caching implementations
- Message queue producers/consumers

## Imports allowed
- Anything from `domain/` and `application/`
- Third-party libraries and SDKs
- `process.env` (environment config lives here)

## Forbidden
- Business logic of any kind
- Direct imports from `interfaces/`
- Leaking ORM/DB types into application or domain layers
- Hardcoded credentials or URLs (use env vars)

## Patterns to follow
- Each repository implementation maps DB rows → domain entities
- LLM clients wrap raw SDK calls behind a clean interface defined in application
- MCP servers are adapters — they translate tool calls into use case invocations
- Infrastructure errors must be caught and re-thrown as domain/application exceptions

## Agent behavior
- Never add logic here — if you find yourself writing conditionals
  based on business rules, that code belongs in domain or application
- Always implement an interface, never create standalone infrastructure classes
