# ADR 0004: GDPR/CCPA groundwork — data export, erasure, and consent

## Status

Accepted

## Context

ApplyFlow is a single-user application. Its one account belongs to the person
who runs it, and that person can already read their own database. So none of
the data-subject rights this document is about bind ApplyFlow today: there is
no data subject who is not also the controller, and no one to answer a request
from.

That is exactly why the work lands now.

The data this application holds is the kind these regimes are written about.
Encryption at rest (`migrations/versions/0021_encrypt_sensitive_columns.py`)
and the log/URL rules (ADR 0003) already treat a candidate's name, address,
résumé text, work authorization, and voluntary EEO self-identification as
material worth building controls around. Rights are the other half of that
posture: encryption answers "who can read this", and export, erasure and
consent answer "what does the person it describes get to decide about it".

The specific reason not to defer it is that the expensive part of these rights
is not the endpoint. It is knowing, exhaustively, where a person's data is. A
codebase that has never had to answer that question accumulates stores that
nobody enumerates — a blob directory, a cache, a table someone added for a
sweep — and the enumeration gets reconstructed later by archaeology, under
deadline, by whoever is on call. Building the enumeration while the schema is
sixteen tables and one person knows all of them costs a day. Rebuilding it at
forty tables costs a quarter and is wrong.

The same argument drove the encryption work and ADR 0003, which is why this
lands immediately after them.

## Decision

### 1. A declared personal-data inventory, and a test that keeps it honest

`src/domain/services/personal_data_inventory.py` declares every category of
personal data this application is responsible for. Each entry states what the
data is, which store holds it, the lawful basis it is held on, whether it goes
into a portable copy, and what an erasure request does to it
(`PersonalDataCategory`).

Export and erasure both iterate this declaration. Neither has its own list.

The alternative — reflecting over the ORM and exporting or deleting whatever
has a `user_id` — was rejected because it is complete-looking and wrong in the
two ways that matter. It cannot see anything outside the database (the résumé
bytes on disk, the prompts sent to a model provider, the application already
sitting in an employer's ATS), and it has no opinion about what it does find,
so a column added next year is handled by whichever default the reflection
happened to have.

What makes the declaration trustworthy is
`tests/infrastructure/test_personal_data_inventory_covers_schema.py`. It
computes, from `Base.metadata` alone, the transitive closure of tables holding
data reachable from a person — a subject column, a `sensitive`-flagged column,
or a foreign key into a table that qualifies — and fails if that set differs
from the tables the inventory declares. Adding a user-scoped table therefore
forces an entry here rather than silently widening the gap. The same file checks
the adapter in both directions: a declared category with no handler, and a
handler for a category nobody declared, are each a build failure.

This is the same convention the sensitive-column work established (a
declaration in metadata plus a test that fails when it drifts) and for the same
reason: a declaration nobody verifies is a comment.

### 2. Export produces everything stored, not everything modelled

`ExportUserData` assembles a portable copy from the inventory's exportable
categories, and `SqlAlchemyPersonalDataStore` reads **rows**, serializing every
column by reflection over the mapper.

Deliberately not via the repositories. Art. 20 asks for "all personal data
concerning him or her", and a domain entity exposes what the domain needs,
which is a subset. Reading columns also means a column added to a table appears
in the export by default — the opposite default from the entity route, and the
safer one.

Three properties of the document are worth naming:

- **It refuses to be partial.** If the adapter's answer is missing a requested
  category, the export raises (`PersonalDataCoverageError`) and the endpoint
  answers 500. A copy short by one section is indistinguishable from a copy of
  someone who had no data in that section — the one failure nobody would
  notice.
- **It lists what it does not contain.** The processor and employer categories,
  and the log sink that holds nothing, appear as `deferred_categories` with the
  note saying who has to act. The user learns where the rest of their data is
  from the export itself, not from this file.
- **It states its own limitations.** `job_applications` predates the account
  model and files rows under an email address, so a request from a token with no
  `email` claim cannot reach them. The export says so rather than reporting an
  empty section, because an empty section reads as "you had none".

Résumé bytes are exported as a manifest (name, type, size, storage key) rather
than inlined base64, with the extracted text of each carried in the `resumes`
section. A portable copy is a JSON document, and a copy that cannot be opened
in the tools someone would use is not portable in any sense that helps them.

### 3. Erasure is driven by the same declaration, and reports what survived

`EraseUserData` deletes exactly the categories dispositioned `ERASE`. Three
decisions inside it:

**Consent is withdrawn before anything is deleted.** The withdrawals go into
the consent ledger, which is the one category deliberately retained. An erasure
that deleted everything would leave an account that merely stopped existing,
with no record that a request was made or honored.

Only consents actually in effect are withdrawn. A purpose the user never
granted is already denied by default; appending "withdrawn" to it would record
a decision nobody made and fill the retained ledger with entries that
demonstrate nothing.

**Order is the adapter's business.** `tracked_applications` references
`application_documents` with `ON DELETE RESTRICT`, so the tracker rows have to
go first. That is a property of the schema, so it lives in
`SqlAlchemyPersonalDataStore._ERASURES` (an ordered mapping, where insertion
order *is* execution order) rather than in the use case, which would otherwise
be encoding foreign keys it is not allowed to know about.

**Blob files are deleted before the rows that name them.** The bytes on disk
cannot join a database transaction, so one of the two orderings had to be
chosen. Files first: a failure then leaves metadata for a file that is already
gone, and a retry finishes the job (the storage delete is idempotent). The
reverse would leave the actual résumé on disk with nothing pointing at it — a
receipt claiming erasure over a file nobody will ever find to clean up.

The receipt reports per-category counts **and** a `retained` list, with the
reason for each. A receipt of deletions alone invites the reader to conclude
the remainder was nothing.

### 4. The consent ledger is retained after erasure

This is the one deliberate exception to "erasure deletes everything", and the
one most likely to be read as a bug.

GDPR Art. 7(1) requires the controller to be able to *demonstrate* that consent
was given. After an erasure the entry that matters most is the withdrawal that
triggered it: deleting the ledger destroys the evidence that the erasure itself
was lawful. Art. 17(3) contemplates exactly this — retention where it is
necessary for compliance with a legal obligation.

What is kept is a purpose, a yes/no, a timestamp, a notice version, and an
account id. No name, address, document, or answer. `consent_decisions` is the
one table in this schema with no encrypted column, and that is load-bearing
rather than incidental: a decision *about* personal data contains none, which is
what makes retaining it defensible rather than a hole in the erasure.

The residual issue is the account id, which is a pseudonymous identifier and
therefore still personal data. At multi-user scale it should become a one-way
digest, so the retained ledger stops being linkable to a person while remaining
countable and auditable. That is item 3 in the deferred work below.

`SqlAlchemyPersonalDataStore` has a reader for this category and no eraser at
all. The retention is a property of the code, not of the caller's argument list
— nothing in this codebase can delete the ledger.

### 5. Consent is per purpose, append-only, and versioned against the notice

Five purposes (`ConsentPurpose`), each carrying its own lawful basis
(`LawfulBasis`). Three consequences fall out of the basis rather than being
coded per purpose:

- **Withdrawability.** Consent is withdrawable by definition; contract is not.
  `ConsentDecision` refuses to construct a withdrawal against a
  non-consent basis, so no path — API, CLI, task, or test — can put an
  unhonorable withdrawal in the ledger. The endpoint answers 409 and points at
  erasure, which is the request that *can* stop that processing.
- **The default.** Consent-based purposes start denied; an unanswered question
  is a "no", not a "not yet objected". Contract-based ones start permitted. A
  user who has never been asked has an empty ledger, and that state has a
  definite answer — which is why the repository returns a record rather than
  `None`.
- **Whether it appears as a toggle.** `ACCOUNT_AND_APPLICATIONS` is
  contract-based and is listed anyway, because the transparency obligation
  covers processing the user cannot switch off. Offering a toggle that cannot be
  honored would be worse than offering none.

The ledger is append-only: one row per decision, keyed
`(user_id, purpose, sequence)` with no surrogate id, mirroring
`application_status_events`. A boolean column cannot demonstrate anything — it
says what the answer is now, and a withdrawal destroys the fact that afterwards
matters most.

Every decision records the `policy_version` it was made against, taken from the
deployment rather than the request body. Consent is only valid for what the user
was actually told, so a materially changed notice invalidates consent collected
under the old one; recording the version makes "who has to be re-asked?" a query
rather than a guess. A client permitted to assert which notice it had shown
could record consent against a notice the user never saw.

`SENSITIVE_ATTRIBUTE_STORAGE` is `EXPLICIT_CONSENT` rather than `CONSENT`. Both
behave identically in code today; the distinction is recorded because Art. 9 is
the thing an auditor asks about and reconstructing it later from a boolean is
not possible.

### 6. Both rights are reachable without the API

`GET /api/privacy/export`, `POST /api/privacy/erasure`,
`GET /api/privacy/consents`, `PUT /api/privacy/consents/{purpose}` — and
`applyflow export-data` / `applyflow erase-data` on the CLI.

The CLI is not a convenience. A subject access request has to be answerable when
the API cannot answer it: no valid token, a frontend that is down, or a request
that arrived by email to an operator. An authenticated endpoint alone would make
the ordinary shape of a real request the one case the design cannot serve.

Both entry points open a `sensitive_data_access` scope, because an export reads
every encrypted column there is. Neither the use case nor the adapter opens
one — a use case that granted itself decryption would be the hole
`sensitive_access.py` exists to close.

No endpoint takes a user id or an email. The subject is whoever the verified
token names, so there is no admin surface here with no authorization story
behind it, and nothing personal reaches a URL (ADR 0003). The only path
parameter is a consent purpose, which names a kind of processing.

## Consequences

- An erasure at single-user scale empties nearly the whole database, which is
  the correct behaviour and also a reason `--confirm` is mandatory on the CLI
  and `acknowledged` is mandatory in the request body. The default for
  `acknowledged` is `false`, so an accidental POST with no body is refused
  rather than honored.
- Adding a user-scoped table now fails the build until it is declared and
  handled. That is the intended cost.
- The export is a synchronous response holding the person's entire record. Fine
  at one user; item 1 below at more.
- `PRIVACY_POLICY_VERSION` is now a deployment setting. Forgetting to bump it
  after a material change to the notice means consent keeps looking valid when
  it is not — the failure mode this field exists to make visible, moved from
  invisible to a one-line config change.
- The `PersonalDataRecord` mapping (`Mapping[str, object]`) is untyped, against
  this codebase's rule about `any` as a shortcut. It is not a shortcut here: the
  payload of a portable copy has to carry everything stored, and typing it as an
  entity would type it as *less* than Art. 20 requires.
- Two categories are honestly deferred rather than quietly omitted — a model
  provider's processing and an employer's copy of a submitted application.
  Both appear in the export and the erasure receipt with the reason and who has
  to act.

## The path to full compliance at multi-user scale

Nothing below is required at one user, and none of it is blocked by the
decisions above. This is the list, in the order it would have to be done.

1. **Asynchronous export delivery.** A synchronous JSON response stops working
   at a real corpus size. The shape: an export job on the existing Celery
   queue, writing to object storage, delivered as a short-lived signed URL, with
   the request and its fulfilment logged. `ExportUserData` is already the unit
   of work — it becomes the task body, and the endpoint returns a job id.
2. **A statutory clock.** GDPR gives one month (Art. 12(3)); CCPA gives 45 days
   with a 45-day extension. That needs a `data_subject_requests` table
   recording receipt, deadline, and fulfilment, because "we answer promptly" is
   not a defensible answer to "when did you receive it?". Follow the
   `consent_decisions` shape: append-only, no personal data beyond the subject
   id.
3. **Pseudonymize the retained consent ledger.** Replace `user_id` with a
   keyed one-way digest on erasure, so the retained demonstration record stops
   being linkable to a person. The blind-index machinery in
   `security/field_cipher.py` already does exactly this transformation.
4. **Identity verification for requests.** Both regimes require the requester
   to be verified before data is handed over or destroyed, and CCPA sets a
   higher bar for deletion than for disclosure. Today the bearer token *is* the
   verification, which is sufficient only because there is one account. At
   multiple accounts this needs re-authentication on the erasure path at
   minimum, and a defined process for requests that arrive outside the app.
5. **Encrypt the blob store.** Called out already as the next increment after
   encryption at rest: `LocalFileStorage` addresses files by opaque key, so the
   directory discloses nothing by itself, but a reader of that directory reads
   résumés. Erasure already reaches these files; confidentiality at rest does
   not yet.
6. **Enforce consent at the point of processing.** *Partly done.* The two
   sensitive profile sections — work authorization and EEO self-identification —
   now require an explicit acknowledgement and record the grant for
   `SENSITIVE_ATTRIBUTE_STORAGE` in the same request that stores the data (see
   `SaveWorkAuthorization` and the profile editor section of the README). That was
   the one site where the gate is unambiguous: the candidate is handing over
   exactly the data the purpose describes, at exactly that moment.

   The rest is still open. The ledger is recorded and exported; nothing else
   *checks* it. `AI_DOCUMENT_GENERATION` should gate the
   generation use cases, `ANSWER_REUSE` the answer-memory writes,
   `AUTOMATED_PORTAL_INTERACTION` the browser paths. Deliberately not done here:
   a gate that silently changes behaviour is worth adding with its own tests and
   its own user-visible explanation of *why* a feature is unavailable, and
   bundling it into the groundwork would have meant shipping five behaviour
   changes inside a data-rights commit. `ConsentRecord.is_granted` is the single
   call each of those sites needs.
7. **Notice at collection, and a real privacy notice.** The `description` and
   `lawful_basis` on every inventory category are written to be the source for
   this — CCPA §1798.100(a) wants the categories enumerated at collection, which
   is the list the inventory already is. Generating the notice from the
   inventory rather than maintaining it separately is what stops the two from
   diverging.
8. **Processor agreements and a records-of-processing register.** Art. 28 needs
   a DPA with each of Anthropic, OpenAI, Adzuna and Tavily; Art. 30 needs a
   register of processing activities. Both are documents rather than code, and
   both are largely transcriptions of the inventory.
9. **Revisit client IP addresses.** ADR 0003 leaves IPs unredacted because the
   ones in these logs belong to outbound ATS and LLM hosts. A
   request-logging middleware would change that, and client IPs are personal
   data. The `application_logs` category is where that reassessment belongs.
10. **Data-retention limits.** Art. 5(1)(e) wants personal data kept no longer
    than necessary, which this application currently does not bound at all — a
    tracked application from four years ago is still stored. That is a product
    decision (how long is a job search relevant?) before it is a technical one,
    and it belongs on the inventory as a per-category retention period.

## Alternatives considered

**Defer the whole thing until there is a second user.** Rejected on the
argument in the Context: the expensive artifact is the enumeration of stores,
and its cost grows with the schema while its value is realized only once
someone needs it. Deferring means building it under deadline, from
archaeology, at the worst moment.

**Reflect over the ORM instead of declaring an inventory.** Rejected. It cannot
see the four stores that are not the database, and it has no place to record
why a category is retained, delegated, or empty — which is most of what makes
an export and a receipt checkable.

**One `accepted_privacy_policy` boolean instead of a consent ledger.**
Rejected. It cannot demonstrate that consent was given (Art. 7(1)), it cannot
express a partial "no", and it destroys the withdrawal record on the write that
matters most. A user who wants their applications stored but their résumé kept
away from a model has, under a single flag, exactly one option: delete
everything.

**Delete the consent ledger along with everything else.** Rejected, and this
was the closest call. It reads as the purer answer to "erase everything", but
it destroys the evidence that the erasure was lawful, which is the record most
likely to be asked for after one. Retaining it is explicitly contemplated by
Art. 17(3), it is declared in the inventory rather than being a silent
exception, and the erasure receipt reports it with the reason — so a reader is
told, not left to discover it.

**Enforce consent at the processing sites in this change.** Rejected as scope.
Six use cases would change behaviour, each needing its own tests and its own
explanation to the user of why a feature went away. Recording consent
correctly is the prerequisite; enforcing it is item 6 above.

**A `data_subject_requests` audit table now.** Rejected as premature. Its
purpose is proving a statutory deadline was met, and there is no requester to
prove it to. Listed as item 2 so it is a known gap rather than an oversight.
