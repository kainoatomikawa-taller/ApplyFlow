# Epic 07 hardening pass — security & privacy verification report

The acceptance gate for Epic 07. Epics 01–06 each built their own half of
ApplyFlow's data protection; Epic 07 added encryption at rest, the log/URL PII
rules, and the GDPR/CCPA groundwork. This pass asked the question none of those
tickets could ask about itself: **do the controls actually hold, together, and
where are the gaps nobody has looked at yet?**

Five areas audited: encryption coverage, log and URL PII hygiene,
sensitive-field enforcement, secrets handling, and dependency/config posture.

**Verdict: all four acceptance criteria are met, after eleven fixes.** The audit
found eleven defects, all fixed here, and seven residual items routed with a
stated path. The most serious finding was not a missing control but a control
that two source files claimed existed and did not.

Nothing in this report was taken on the strength of reading the code. Every fix
is pinned by a test, every new guard was mutation-tested by reintroducing the
defect it exists to catch, and the schema migration was verified end to end
against a real Postgres seeded with plaintext.

---

## H1 — the keystone guard did not exist — FIXED

**Severity: high.** `models.py` and `encrypted_types.py` both name
`tests/infrastructure/test_sensitive_column_coverage.py` as the mechanism that
keeps the `sensitive` flag and the encrypted column type in lockstep:

> The tag and the encryption are kept in lockstep by a test that walks this
> metadata (`tests/infrastructure/test_sensitive_column_coverage.py`) and fails
> if a sensitive-flagged column is stored in the clear — so adding a column here
> and flagging it is enough to be told that it also needs encrypting.

That file did not exist. Neither did
`tests/infrastructure/test_encryption_at_rest.py`, referenced by **eight**
persistence smoke tests as "the tests that assert the refusal when no scope is
open".

This is the worst failure mode available to a control: the codebase asserted a
safety net in nine places, a reviewer had every reason to believe it, and nothing
checked. The eight smoke tests all *open* an access scope, so they proved
decryption works — nothing proved it stops. A gate accidentally disabled (a scope
opened at import, a `require_` call dropped from the decrypt path) would have
left the whole suite green.

Both files are now written.

**`test_sensitive_column_coverage.py`** (14 tests, no database) walks
`Base.metadata` and checks four groups:

1. **Flag ⇔ encryption**, both directions. An encrypted-but-unflagged column is
   protected at rest and invisible to every other control that reads the flag.
2. **Purpose strings** are exactly `table.column`, and no two columns share one.
   The purpose is authenticated into the ciphertext, so a typo does not fail at
   deploy time — it writes rows that decrypt nowhere, discovered whenever someone
   finally reads that column.
3. **Storage shape**: `Text`, no server default, not indexed. Each has bitten
   this codebase or was one edit from it — migrations 0021 and 0023 both had to
   drop a `server_default` that would otherwise insert plaintext, and an index on
   randomized ciphertext can serve no query.
4. **Nothing free-text left undecided** — see H2 for why this is the group that
   earns its keep.

**`test_encryption_at_rest.py`** (40 tests, no database) covers the gate and the
cipher's promises: refusal with no scope, scope teardown, nesting, the refusal
through the ORM column types, randomized nonces, tamper detection, cross-column
rejection, plaintext-in-column raising rather than passing through, envelope
version and nonce validation, key rotation across a retired key, the
unknown-key error, the development-fallback key being identifiable, and the blind
index being deterministic, keyed, and purpose-separated.

**Verified to have teeth.** Eight mutations reintroduced, each caught:

| Mutation | Caught by |
| --- | --- |
| `require_sensitive_data_access` removed from `decrypt` | 4 failures |
| `purpose` dropped from the GCM authenticated data | cross-column test |
| Plaintext passed through instead of refused | 2 failures |
| Free-text column added to a personal table, unflagged | free-text ruling test |
| Column flagged sensitive but left in the clear | 2 failures |
| Purpose typo (`postal_code` bound as `zip_code`) | purpose test |
| `server_default` added to an encrypted column | server-default test |
| Index added to an encrypted column | index test |

---

## H2 — a cover letter stored in plaintext — FIXED

**Severity: high.** `job_applications.tailored_cover_letter` held a full cover
letter — written from the candidate's profile, so their name, contact details and
employment history in prose — in the clear.

One table over, `application_documents.content` holds exactly this class of
document and is encrypted, with the reasoning stated in its own docstring:

> A document derived from those inputs inherits their classification rather than
> a milder one.

That argument applies verbatim. `job_applications` is the Epic 00/01 predecessor
of the documents table and was simply missed when the flags were drawn up.

Note what did **not** find this. H1's lockstep guard checks that a column
*someone remembered to flag* is encrypted. This column was never flagged, so a
flag-based check would have passed it forever. That gap is now closed by
`test_every_free_text_column_has_been_ruled_on`: every `Text`/`JSON`/long-`String`
column on a table the personal-data inventory covers must be either encrypted or
listed in `_REVIEWED_PLAINTEXT` **with a reason**. Adding one forces a decision,
and the decision is written where the next reviewer can disagree with it.

Fixed by migration 0023.

---

## H3 — one of three identical note columns was unencrypted — FIXED

**Severity: medium.** `application_status_events.note` is free text the candidate
typed about a status change. It was in the clear, on the reading recorded in its
own comment — "not sensitive the way a document is".

No principle separates it from `application_reviews.submission_note` and
`portal_handoffs.resolution_note`, which are the same thing (a note the candidate
typed, unconstrained in content) and were both encrypted by migration 0021. Three
free-text note columns with two different answers is an inconsistency, not a
distinction.

The examples in `ApplicationStatusChange`'s own docstring settle it: *"referred by
Dana"* names a third party who never consented to being in this database at all.

Fixed by migration 0023.

### Migration 0023, verified end to end

Against a real Postgres seeded with known plaintext, following the practice
established for 0021 rather than only unit-testing it:

- both columns became `encv1:` envelopes at rest;
- both decrypted back to the exact original strings;
- the `note` column's `server_default` of `''` was dropped (it would otherwise
  insert plaintext nothing can decrypt — the same trap 0021 documented);
- purpose binding confirmed: the cover-letter ciphertext refuses to decrypt as
  `application_status_events.note`;
- `downgrade()` restored both to plaintext and restored the default;
- re-upgrade clean. 1,098 existing note rows and the seeded letter converted.

`application_status_events` has a composite primary key
(`tracked_application_id`, `sequence`) with no surrogate id, which 0021's
single-key row-addressing helper could not handle — so 0023 keyset-paginates on
the full key rather than reusing it.

---

## H4 — connection-string credentials were never redacted — FIXED

**Severity: high.** ADR 0003 installs a process-wide log scrubber and states that
stripping a URL's query string is what contains an outbound credential. It has no
rule for the *other* place a URL keeps a secret: the userinfo, before the `@`.

Every connection string in this deployment keeps its password there. Measured
before the fix:

```
IN : connecting to postgresql+asyncpg://applyflow:sup3rs3cret@db:5432/applyflow
OUT: connecting to postgresql+asyncpg://applyflow:sup3rs3cret@db:5432/applyflow
IN : redis://:myredispassword@cache:6379/0 unreachable
OUT: redis://:myredispassword@cache:6379/0 unreachable
IN : database_url=postgresql://applyflow:sup3rs3cret@db:5432/applyflow
OUT: database_url=postgresql://applyflow:sup3rs3cret@db:5432/applyflow
```

The third line is the sharpest: `database_url` was not even in the scrubber's
sensitive-key list, so the labelled form leaked too.

And these DSNs do reach logs. An asyncpg or SQLAlchemy connection failure
stringifies the DSN it was dialing — this repository's own smoke-test skip
message is `f"No reachable database at DATABASE_URL: {exc}"`. The one credential
guaranteed to exist in every environment was the one nothing scrubbed.

`_URL_CREDENTIAL_RE` now redacts the userinfo of any scheme, keeping the host and
port (which is all a connection-failure line is diagnostic for) and dropping the
username with the password. It is ordered **before** the email rule: a userinfo
pair like `admin:pw@mail.example.com` contains something the email pattern
matches, so the reverse order would rewrite the middle of the DSN and strand the
password's leading characters outside the marker.

---

## H5 — hyphenated credential key names were unmatched — FIXED

**Severity: low.** The scrubber's key names are snake_case, and `\bapi_key\b`
does not match `api-key` — so `x-api-key: sk-ant-api03-...` and
`x-auth-token: ...`, the spellings an HTTP client's error or a header dump
prints, passed through.

`_alternation` now renders each `_` as `[-_]`, so every name matches either
spelling. Only the separator is widened — the names themselves are unchanged, so
this cannot start matching a word that was not already listed. Verified against
the telemetry lines this project has been bitten by before:
`cache_read_input_tokens=500`, `cache-read-input-tokens=500` and
`keyword=engineer` all survive intact.

---

## H6 — SQL echo defeated the entire log-PII control — FIXED

**Severity: high.** `DEBUG` defaults to `True` and was wired straight into
SQLAlchemy's `echo`, which logs every statement **with its bound parameters**.

Parameters arrive as a positional tuple. The scrubber recognizes a value either
by its shape or by an adjacent key name, and a bare tuple offers neither — so
exactly the categories ADR 0003 documents the scrubber as unable to see pass
through untouched. Measured:

```
IN : [generated in 0.00021s] ('Jane Okonkwo', '17 Bellwether Lane',
      'Acme Robotics', 'Dear hiring manager, I am Jane...')
OUT: unchanged
```

One forgotten `DEBUG=false` was therefore sufficient to write whole candidate
records, in the clear, into a log sink that sits outside the encryption boundary
and has no key rotation. Every other Epic 07 control — the cipher, the access
gate, the call-site guard — would have held while this bypassed all of them.

`sql_echo_enabled(settings)` now requires `environment == "development"` as well
as `debug`. Deliberately **not** solved by refusing `DEBUG=true` in production:
verbose logging is a legitimate thing to want during an incident, and a control
that forces someone to choose between diagnosis and privacy is a control that
gets switched off.

`tests/infrastructure/test_sql_echo_is_gated.py` pins the gate, and — more
importantly — pins the *reason* for it, by asserting that the scrubber genuinely
cannot clean up after echo. Without that second test, someone could reasonably
conclude redaction already covered this and remove the gate.

---

## H7 — connection strings were not `SecretStr` — FIXED

**Severity: medium.** `database_url`, `redis_url`, `celery_broker_url` and
`celery_result_backend` were plain `str` while every API key was `SecretStr`, so
any `repr(settings)` — a debug dump, a stray `print`, an exception rendering its
context — spelled out the database password.

All four are now `SecretStr` (four settings, five call sites). Verified: the
password no longer appears in `repr(settings)` or `str(settings)`, and alembic
and the full suite still run.

`test_every_credential_bearing_setting_is_a_secret_str` asserts this over
`model_fields` rather than a fixed list, so a fifth URL or a new API key has to
make the same decision. The predicate is **suffix**-matched, not
substring-matched: `"token" in name` would have claimed `anthropic_max_tokens`,
which is the same trap the scrubber's key names document.

H4 and H7 are the same leak addressed at two independent layers, deliberately —
both are cheap and they fail independently.

---

## H8 — the image would have baked in secrets and résumés — FIXED

**Severity: medium.** `.dockerignore` excluded `.env` but not `.env.local`.
`Settings.model_config` reads **both** (`env_file=(".env", ".env.local")`), so a
developer's `.env.local` holds the same API keys and the same
`FIELD_ENCRYPTION_KEYS` — and `COPY . .` would put it in a distributable image
layer. The file the application actually prefers was the one not excluded.

`var/` was also missing: that is `resume_storage_dir`, holding real candidate
PDFs. Baked into an image layer they outlive any erasure request and travel
wherever the image does.

Both excluded now (`.env`, `.env.*`, `var/`).

---

## H9 — `.gitignore` covered only two environment files — FIXED

**Severity: low.** `.env` and `.env.local` were ignored; `.env.production` and
`.env.staging` were not, and are just as easy to create. Broadened to `.env.*`
with `!.env.example` so the template stays tracked. Verified with
`git check-ignore`, and `.env.example` confirmed still tracked.

---

## H10 and H11 — the two sensitive-field findings left open — FIXED

`docs/sensitive-field-enforcement-check.md` routed two defects as "Epic 01/05
rule-tuning rather than verification work". They are live wrong values in legal
fields, so this pass closed them.

**H10 (was F2, medium):** *"Have you ever been sponsored for a visa?"* and *"Are
you currently on a visa sponsored by your employer?"* fall past the sponsorship
rules — which need the token `sponsor`/`sponsorship`, not `sponsored` — to the
bare `visa` rule, and resolve to `VISA_TYPE`. A visa holder got `"H-1B"` written
into a yes/no question.

**H11 (was F3, low):** *"Work permit expiry date"* matches the `work permit` rule
and resolves to `WORK_AUTHORIZATION`, which answers Yes/No — so `"Yes"` went into
a field asking for a date.

Both were contained on selects and radios, which refuse a value they have no
option for and surface the field. Both were written on a **text** input.

Shared root cause with the already-fixed F1: the sensitive label rules are
greedy, matching one phrase without asking whether the label poses a *different*
question than the slot's canonical one. Neither sponsorship history nor any date
is something the profile stores, so under exact-or-refuse the answer is to
refuse.

`_asks_something_no_stored_field_states` now surfaces a label that matches one of
the three current-state legal slots and also carries a date or history qualifier
(`expiry`, `expiration`, `expires`, `expire`, `expiring`, `date`, `until`,
`sponsored`, `ever`, `previously`).

Scoped as narrowly as F1's fix was, and for the same reason — the previous fix
was careful not to refuse the canonical questions, and this one must not undo
that. Confirmed still answered: *"Will you now or in the future require
sponsorship for employment visa status?"*, *"Do you require visa sponsorship?"*,
*"Are you legally authorized to work in the United States?"*, *"What is your visa
type?"*, *"Visa status"*, *"Citizenship status"*, *"Country of citizenship"*. And
`valid` is deliberately **not** a qualifier — only `until` — so *"Is your work
authorization valid?"* still resolves.

Seven new cases in `tests/acceptance/test_sensitive_field_enforcement.py`
(118 total, up from 111). Mutation-tested: reverting the guard fails six of them.

---

## What was verified per acceptance criterion

### AC1 — sensitive data encrypted at rest, no gaps

**Met.** 30 columns flagged and encrypted, flag and encryption in exact
agreement (28 from migration 0021, plus the two H2/H3 columns).

The stronger claim — "no gaps" — rests on the free-text ruling test, not on the
flag check. Every free-text column on a personal-data table is now either
encrypted or recorded in `_REVIEWED_PLAINTEXT` with a reason; there are 24 such
recorded entries, each stating why the column is safe in the clear. Three
categories: the employer's own data (company, role, posting text, apply URLs),
derived metadata that describes personal data without containing it
(`backing_sources`), and the candidate's structured CV facts — which are the one
accepted residual risk, tracked as R1 below.

Crypto design reviewed and found correct: AES-256-GCM; the additional
authenticated data binds envelope version, key id **and** `table.column`, so a
ciphertext moved between columns fails to decrypt; random 96-bit nonce per
encryption, so equal values are not equal at rest; keyring with per-value key ids
enabling rotation without a rewrite-the-world migration; blind index is a keyed
HMAC with the purpose mixed in, so one column's index cannot probe another's;
error messages carry the `table.column` and never the value.

Decryption remains scoped to the four authorized entry points
(`get_current_user`, the Celery analysis task, the CLI, and the data-rights CLI
commands), each naming its subject and reason.

### AC2 — no PII in logs or URLs, verified by audit

**Met, after H4, H5 and H6.**

- **URLs.** `tests/interfaces/http/test_no_pii_in_urls.py` passes: no route
  parameter, path or query, on any endpoint carries a personal identifier, and
  the frontend client's URL templates are clean. The privacy endpoints added for
  the GDPR work take no identifier at all — the subject is the token's — and
  their one path parameter is a consent purpose, which names a kind of processing.
- **Log call sites.** `test_pii_log_call_sites.py` passes across all of `src/`,
  and every one of the 30 sensitive columns is a decided case
  (`tailored_cover_letter` banned outright; `note` recorded as too generic to
  match statically, covered by the runtime scrubber's labelled form).
- **The scrubber**, measured rather than assumed, against emails, phones,
  national IDs, Luhn-valid cards, JWTs, bearer tokens, query strings, labelled
  values, DSN userinfo (H4) and hyphenated header keys (H5) — and against the
  operational lines that must survive.
- **SQL echo** no longer reaches a non-development log sink (H6).
- **Frontend**: no `console.*` calls anywhere in `frontend/src`.

### AC3 — sensitive-field policies verifiably enforced end to end

**Met.** The 118-case acceptance suite covers all thirteen
`WorkAuthorizationStatus` × `requires_sponsorship` combinations driven from a
stored profile through to the bytes written to the page, the four independent
levels of EEO refusal, the tailoring path, and — new in this pass — the
questions the record cannot answer (H10, H11).

Profiles round-trip through the real persistence mappers, so the policy reads
what storage would return. With H2 and H3 encrypted, that round trip now also
exercises two more encrypted columns.

### AC4 — documented multi-user compliance path; findings tracked to closure

**Met.** `docs/decisions/0004-gdpr-ccpa-groundwork.md` carries the compliance
path as a ten-item ordered list. This report is the closure record: eleven
findings fixed with tests, seven routed below with a stated path and owner-level
next action. Nothing found in this pass is undocumented.

---

## Routed — open, with a path

**R1 — CV facts in the clear (medium).** `work_history_entries`,
`education_entries`, `skills` and `user_profiles.headline` hold the candidate's
employment and education history unencrypted. Epic 07 drew its boundary at
contact details, legal declarations, free-text answers and whole documents, and
said so — but the same facts *are* encrypted one table over, in
`resumes.extracted_text`, which makes this an inconsistency rather than a clean
scope line. Closing it is ~10 columns on 4 tables, mechanically identical to
migration 0023, and costs the ability to filter or sort on them in SQL (nothing
currently does). Recorded in `_REVIEWED_PLAINTEXT` so it stays visible.

**R2 — the container runs as root (low).** No `USER` directive in the Dockerfile.
Deliberately not fixed here: Docker was unavailable in this environment, and an
unverified change to the only deployment artifact is worse than a recorded
finding. The change is `useradd` + `chown` + `USER`, and the specific thing to
check is that it still works under the compose bind mount (`.:/app`), because
`LocalFileStorage.__init__` does `mkdir(parents=True)` on `var/resumes` at
startup and would fail as a non-root user against a root-owned directory. Also
worth folding in: a multi-stage build, so `build-essential` does not ship.

**R3 — no dependency lockfile (medium).** Every requirement is floor-pinned
(`>=`), so no two builds necessarily resolve to the same versions and a
compromised release is picked up silently. The good news is measured: `pip-audit`
reports **zero known vulnerabilities** across the runtime dependencies at the
versions resolving today (fastapi 0.141.1, sqlalchemy 2.0.51, cryptography
50.0.0, pyjwt 2.13.0, anthropic 0.120.2, starlette 1.3.1, and the rest). The 13
findings it reports are in `pip` 24.0 and `setuptools` 65.5.0 — the local venv's
own bootstrap tooling, not the application image, whose Dockerfile upgrades pip.
Path: `pip-compile --generate-hashes` into a `requirements.lock`, plus `pip-audit`
in CI so this becomes continuous rather than a snapshot in a report.

**R4 — CORS origins hardcoded (low).** `create_app` hardcodes
`http://localhost:5173` and `http://localhost:3000` with
`allow_credentials=True`. Not a vulnerability as written — it is not a wildcard —
but a production deployment has to change it, and the shortest path from "our
frontend can't call the API" to "shipped" is `allow_origins=["*"]`, which with
credentials enabled is a real hole. Move it to config with the deployment's own
origin.

**R5 — the compound question is surfaced, not answered (low).** Carried over
from `docs/sensitive-field-enforcement-check.md`: answering *"authorized to work
without sponsorship?"* exactly needs a `WORK_AUTHORIZATION_WITHOUT_SPONSORSHIP`
slot deriving from authorized-AND-not-requiring-sponsorship. Surfacing it is
correct-but-inconvenient, so this is an improvement rather than a defect.

**R6 — the blob store is not encrypted.** `LocalFileStorage` addresses files by
opaque key, so the directory discloses nothing by itself, but a reader of that
directory reads résumés. Erasure already reaches these files (Art. 17);
confidentiality at rest does not. Already item 5 of ADR 0004's path.

**R7 — consent is recorded but not enforced.** `ConsentRecord.is_granted` exists
and nothing calls it. Already item 6 of ADR 0004's path, with the six call sites
named.

---

## Confirmed non-issues

Checked and found correct; recorded so they are not re-investigated.

- **JWT verification.** Algorithm pinned to `HS256` in `algorithms=[...]`, so
  the `alg: none` and RS256/HS256 confusion attacks do not apply; audience
  checked against `authenticated`; `sub` required; expiry checked by PyJWT's
  default; an unconfigured secret is refused rather than treated as empty. The
  error message returned to the client carries PyJWT's reason and never the
  token.
- **No secrets in the repository.** No `.env`, key, or PEM file is tracked; a
  scan for private-key blocks, `sk-` keys, AWS access-key ids and JWTs found
  nothing. `.env.example` is placeholder-only, enforced by
  `test_env_example_documents_every_key_without_real_values`.
- **The development encryption key cannot reach production.** `Settings`
  refuses an empty `FIELD_ENCRYPTION_KEYS` or `FIELD_BLIND_INDEX_KEY` outside
  `development`, and the fallback key id is the literal `dev-insecure`, so a row
  written under it is visible as such in a `SELECT`. Both now tested.
- **`docker-compose.yml`'s `applyflow:applyflow` credentials** are a local dev
  stack (`--reload`, source bind-mounted), not a deployment artifact. It sets no
  `FIELD_ENCRYPTION_KEYS`, so it uses the development key by design.
- **The frontend stores the access token in `localStorage`.** Exfiltratable by
  an XSS, and the documented tradeoff Supabase's own client makes; the token is
  short-lived and this is a single-user app. Accepted, and worth revisiting
  alongside R7 if the app ever becomes multi-user.
- **Client IP addresses are not redacted.** Unchanged ADR 0003 decision: the
  addresses in these logs belong to outbound ATS and LLM hosts. Still the first
  thing to revisit if request-logging middleware is ever added — recorded in the
  `application_logs` category of the personal-data inventory.
- **The personal-data inventory and its schema guard** pass, so the export and
  erasure paths still account for every table holding personal data — including
  the two columns H2 and H3 encrypted, which changed their protection but not
  their category.

---

## Running the checks

```bash
pytest tests/infrastructure/test_sensitive_column_coverage.py    # 14, flag<->encryption
pytest tests/infrastructure/test_encryption_at_rest.py           # 40, the gate + cipher
pytest tests/infrastructure/test_pii_log_redaction.py            # 42, the scrubber
pytest tests/infrastructure/test_pii_log_call_sites.py           # static log guard
pytest tests/infrastructure/test_sql_echo_is_gated.py            # 5, the echo gate
pytest tests/interfaces/http/test_no_pii_in_urls.py              # static URL guard
pytest tests/acceptance/test_sensitive_field_enforcement.py      # 118, end to end
pytest tests/infrastructure/test_personal_data_inventory_covers_schema.py
pytest tests/infrastructure/test_config.py                       # secrets typing
```

None is gated behind an env var, and only the persistence smoke tests need a
database. Suite total after this pass: 2,060 passing.

One pre-existing failure is unrelated and known:
`test_job_posting_persistence_smoke.py::test_requirements_round_trip_against_a_real_database`
fails on a clean tree because the shared dev database has accumulated more than
1,000 `job_postings` rows, pushing the newly inserted row outside the query's
`limit`.
