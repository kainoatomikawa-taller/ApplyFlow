# ADR 0003: Keep PII out of logs and out of URLs

## Status

Accepted. **Amended** by the Epic 07 hardening pass — see
`docs/epic-07-hardening-check.md`. The decisions below stand unchanged; three
gaps in their *implementation* were found and closed:

- the URL rule stripped query strings but not userinfo, so every connection
  string's password (`postgresql://user:pw@host`) passed through unredacted (H4);
- credential key names were snake_case only, so header spellings like
  `x-api-key:` did not match (H5);
- SQLAlchemy's statement echo, wired to `DEBUG` (default `True`), logged bound
  parameters as a positional tuple — no shape, no key names — which bypassed
  §3's guarantee for exactly the shapeless categories it names. Echo is now
  gated to development (H6).

## Context

Encryption at rest (`migrations/versions/0021_encrypt_sensitive_columns.py`
and `src/infrastructure/security/`) put the candidate's name, address, phone,
email, résumé text and answers behind a cipher and a `sensitive_data_access`
gate. That protects the database. It protects nothing about the two places
the same data leaks *without* going through the database:

1. **Logs.** A log line is written in plaintext, shipped to wherever the
   deployment ships logs, and retained on a schedule nobody consults. It sits
   entirely outside the encryption boundary, and there is no key rotation for
   a log sink.
2. **URLs.** A query string or path segment is the least private part of a
   request. It is recorded by default in web-server and proxy access logs,
   CDN logs and browser history, and it is handed to third parties in the
   `Referer` header. None of that is under this application's control, and
   none of it can be purged after the fact.

Both are cheap to get right early and expensive to retrofit — the same
argument that drove the encryption work, which is why this lands immediately
after it rather than later.

The audit that prompted the specifics found:

- `GET /api/applications?candidate_email=...`, called by the frontend with
  the candidate's address URL-encoded into the query string.
- Two log sites writing verbatim document text: an ATS-safety violation
  logging a résumé line, and the provenance guard logging a stripped line.
- Adzuna's `app_key` in an outbound query string, reachable in logs via a
  stringified `httpx` error.

## Decision

### 1. Sensitive identifiers never travel in a URL

`GET /api/applications` now reads the candidate from the verified bearer
token's `email` claim; the query parameter is gone rather than relocated.
This is a single-user application, so the token's identity was the only
legitimate value the parameter could ever have carried — it was an
authorization hole as much as a privacy one.

A token with no `email` claim gets a 400, so a misconfigured auth provider
fails loudly instead of rendering an empty list.

The rule is enforced on both ends of the wire by
`tests/interfaces/http/test_no_pii_in_urls.py`: the API's published URL
surface is read off the generated OpenAPI schema, and the frontend client's
URL templates are scanned as source, because the backend cannot reject a
parameter it never declared but the browser will still have recorded it.

Outbound third-party calls are held to the same rule where the third party
allows it — the search provider takes its credential in an `Authorization:
Bearer` header, and its query travels in a POST body rather than a query
string, which matters because a search term can be a candidate's name. Adzuna's
public API accepts no header alternative, so its `app_id`/`app_key` stay in the
query string; see below for how that is contained.

> **Provider change, 2026-08-04.** This originally read "Brave Search takes its
> credential in an `X-Subscription-Token` header". Brave withdrew its free tier
> and the implementation moved to Tavily (`TavilySearchClient`). The decision is
> unchanged and Tavily satisfies it slightly better: Brave put the query in a
> URL, Tavily puts it in a body.

### 2. Logging redacts PII process-wide

`src/infrastructure/observability/` installs a `logging` record factory in
each process entry point (HTTP `create_app`, the Celery `setup_logging`
signal, the CLI `main`, and `tests/conftest.py`). Every `LogRecord` created
anywhere — including in `application/`, which cannot import infrastructure,
and in uvicorn, SQLAlchemy and Celery, which have never heard of us — passes
through it.

A record factory rather than a filter or a formatter, because filters and
formatters attach to *handlers*, and a logger with `propagate = False` and a
handler of its own (`uvicorn.access` is exactly that) never reaches the root
handler they were attached to. The factory has no such gap. The filter and
formatter are installed too, covering the two paths a factory misses: records
rebuilt by `makeLogRecord` for queue/socket shipping, and a formatter that
re-renders `exc_info` instead of reusing `exc_text`.

It redacts values with a recognizable shape — emails, phone numbers,
national IDs, Luhn-valid card numbers, JWTs and bearer tokens, whole URL
query strings — and values labelled by a sensitive key name
(`street_address=`, `'full_name':`). It runs over the rendered message, the
rendered traceback, and `extra=` strings.

Stripping the whole query string from any URL is what contains the Adzuna
credential: the retry logging can pass an `httpx` exception straight through
because the URL in it loses its query before any handler sees it. Scheme,
host and path survive, which is all the retry logs were ever for.

### 3. What the scrubber cannot do, the call sites must

Pattern matching cannot recognize a person's name, a street, or the prose of
an answer they wrote — "Sarah Okonkwo" is indistinguishable from "Acme
Robotics" to a regex. So those are kept out by never being logged, and
`tests/infrastructure/test_pii_log_call_sites.py` enforces it: it parses
every module under `src/`, finds each `logger.<level>(...)` call, and fails
if an argument reads a field known to carry personal data. A
`# pii-ok: <reason>` comment suppresses a call; the reason is mandatory.

The banned-name list is tied to the encryption work by a test asserting that
every `sensitive`-flagged ORM column is either banned or explicitly listed as
too generic to match statically — so adding a sensitive column forces a
decision rather than silently widening the gap.

Two log sites were remediated under this rule:

- **`_log_ats_findings`** logged the offending résumé line. It now logs the
  rule, its `detail` sentence, and the line number. Every ATS rule is about
  *formatting* — markdown syntax, table markup, decorative glyphs — so what
  to fix is described by the rule, not by the candidate's employment history.
  The document itself is stored encrypted and readable through an authorized
  path, which is where someone who needs to see line 12 should go.
- **`GenerationGuardAudit`** logged the stripped line, on the reasoning that
  an unsupported line must be model invention rather than candidate data.
  That reasoning does not hold: the guard strips a line because the *claim*
  is unsupported, which says nothing about the other words in it. "Sarah
  Okonkwo led a team of 40 at Initech" is stripped for the team of 40, and
  the name in front of it is real. It now logs
  `violation.unsupported_terms`, which was always the actionable signal.

## Consequences

- Log lines lose some detail. A redacted line keeps its label
  (`email=[redacted:value]`), so it still says what kind of thing was
  removed.
- Over-redaction is chosen over under-redaction, with one known cost: an
  unquoted value after a sensitive key runs across spaces until the next
  `key=`, so trailing prose is redacted with it (`app_key=s3cret failed`
  loses the "failed"). Quoted and comma-delimited values — what reprs and
  this codebase's own log lines produce — are unaffected.
- Lazy `%`-formatting is given up: a rule has to see interpolated text to
  catch an email that arrived as an argument. This application does not log
  at a volume where that matters.
- IP addresses are deliberately **not** redacted. They are personal data
  under GDPR, but the addresses appearing in these logs belong to outbound
  ATS and LLM hosts rather than to the candidate, and redacting them would
  cost the retry/backoff logging its diagnostic value while protecting
  nobody. **If a request-logging middleware is ever added, revisit this** —
  client IPs are a different question from server IPs.
- The frontend's "Viewing applications for" email input is gone. It had
  nothing left to control once the backend stopped accepting the parameter.

## Alternatives considered

**Redaction only, no call-site rule.** Rejected: names and free text have no
shape, so the scrubber cannot see them. It would have given the appearance of
coverage over the largest category of candidate data in the app.

**Call-site rule only, no redaction.** Rejected: several log lines carry text
this codebase did not compose (a quoted résumé line, a stringified request
URL) and tracebacks are rendered by the logging machinery. Whether personal
data is inside them is a runtime property no reviewer can settle by reading
the code.

**Moving `candidate_email` from the query string into a request header.**
Rejected: it treats the symptom. The parameter should not have existed —
deriving the candidate from the token removes the leak *and* the
authorization hole, and leaves nothing to keep in sync.

**A `structlog`-style structured-logging migration.** Rejected as out of
scope. It would be a better foundation for redaction, but it means rewriting
all 52 log sites; the record factory delivers the same guarantee against the
logging the codebase already has.
