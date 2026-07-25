# Epic 04 acceptance check — the tailoring engine

Epic 04 built the tailoring engine: requirement-gap detection, the
gap-resolution question loop with its cross-application answer memory,
provenance-guarded generation of a tailored resume and a cover letter,
ATS-safe output, and the immutable snapshot of the exact text that was
sent. This document is the Definition of Done for that epic, and the flow
`tests/acceptance/test_epic04_tailoring_pipeline.py` proves it end to end
against real infrastructure.

## What "done" means

1. For a chosen job, one flow detects the candidate's gaps, runs the
   question loop over them, and generates both documents.
2. Every line of both documents traces to a provenance-backed fact — no
   fabrication, even when the posting is actively asking for something the
   candidate cannot back.
3. The output is ATS-safe, and the exact versions that were produced are
   stored and readable back unchanged.

## The "asked for both, has only one" case

The sharpest test of criterion 2 is a single posting that asks for two
things the candidate's stored record does not mention — one the candidate
genuinely has, one they do not:

| Requirement | Candidate's real position | Expected outcome |
| --- | --- | --- |
| **Kafka** (preferred skill) | has the experience, it just isn't on file | detected as a gap, asked about, answered truthfully → captured as an `answer`-provenance fact → may legitimately appear in the documents |
| **Kubernetes** (required skill) | no experience | detected as a gap, asked about, **declined** → nothing stored → must appear nowhere in either finished document |

Both directions matter. Failing the first would make the question loop
pointless: the candidate volunteered real experience and the engine threw
it away. Failing the second is the failure mode the whole provenance
pipeline exists to prevent — the posting names the skill, the model is
under direct pressure to claim it, and an LLM told "only use these facts"
still writes "experience with Kubernetes" often enough that prompt
instructions cannot be the control. `ProvenanceGuard` is the mechanical
gate that makes the second row a property of the system rather than a hope
about the model.

The same case also separates *declining* from *answering*: a declined gap
leaves no `AnswerMemory` row at all, so the next pass of the question loop
still asks about it, while the answered gap is suppressed.

## Running it

The check is opt-in — it hits a real Postgres database, the real HTTP app
with real Supabase-JWT auth, and makes real LLM and embedding calls (gap
detection and question phrasing on the cheap tier, the resume and cover
letter on the strong tier, plus one embedding per question and per stored
answer):

```bash
RUN_EPIC04_ACCEPTANCE_TEST=1 pytest tests/acceptance/test_epic04_tailoring_pipeline.py -v -s
```

Requires, via `.env` or exported env vars:

- `DATABASE_URL` — a reachable Postgres (`docker compose up db` locally, or a Supabase project)
- `SUPABASE_JWT_SECRET` — used both to mint the test's bearer token and by the app to verify it
- `ANTHROPIC_API_KEY` — a pay-as-you-go key (see `AnthropicLlmClient`)
- `OPENAI_API_KEY` — Anthropic has no embeddings endpoint, so answer memory's
  similarity matching runs through `OpenAiEmbeddingClient`

Without `RUN_EPIC04_ACCEPTANCE_TEST=1` set, the test is skipped — the
regular `pytest` run never touches a real database or spends money.

## What the flow does

0. **The auth gate first.** `POST /api/job-postings/{id}/tailored-resume`
   with no `Authorization` header must return `401`. This runs before
   anything else deliberately: if the gate ever stops holding, the run
   fails before it pays for a document nobody was authorized to request.

1. **Seed one candidate + one posting directly through the repositories**
   (`SqlAlchemyProfileRepository`, `SqlAlchemyJobPostingRepository`) — this
   check exercises the tailoring engine, not resume parsing or job
   ingestion, so the record is hand-built rather than parsed and crawled.
   - The candidate: contact details, address, a GitHub link, two roles
     (Northwind Freight, Harborlight Analytics), a BS in Computer Science,
     four skills (Python, PostgreSQL, FastAPI, Docker), U.S. citizenship.
     Provenance is split on purpose — contact/address/links are
     `user_entered`, work history/education/skills are `parsed_resume` — so
     the finished documents have to trace to more than one source.
   - Nothing in the record mentions Kafka or Kubernetes.
   - The posting: `required_skills=("Python", "PostgreSQL", "Kubernetes")`,
     `preferred_skills=("Kafka",)`, `min_years_experience=5`.

2. **`GET /api/job-postings/{id}/gaps`** — the real
   `LlmRequirementGapDetector` reads the classified requirements against
   the candidate's facts and answers. Asserts the gap list is non-empty and
   names both Kubernetes and Kafka (criterion 1).

3. **`POST /api/gap-resolution/questions`** with that gap list — asserts one
   question per gap, in input order, none of them empty, and
   `already_answered` empty (this candidate has answered nothing yet).

4. **`POST /api/gap-resolution/answers`**, once per gap:
   - the Kafka question gets a truthful answer in the candidate's own words
     → `captured=true` with an `answer_memory_id`.
   - every other gap, Kubernetes included, gets `"no experience"` — one of
     the forms `GapAnswerPolicy` recognizes → `captured=false`,
     `answer_memory_id=null`.
   - then, read through `SqlAlchemyAnswerMemoryRepository`: **exactly one**
     row exists for this user, it is the Kafka answer, and its source is
     `answer`. That is what "cleanly omits the item" means — a decline
     leaves no row, not an empty one.

5. **`POST /api/gap-resolution/questions` again**, same gaps — asserts the
   Kafka gap now comes back under `already_answered`, pointing at the stored
   `answer_memory_id`, while the declined gaps are still asked. The question
   is regenerated from scratch on this pass and its wording differs, so the
   match is semantic (`AnswerSimilarityMatcher` over real embeddings) at the
   production default threshold — a failure here means answer memory is not
   actually suppressing rewordings, which is the whole point of storing it.

6. **`POST /api/job-postings/{id}/tailored-resume`** and
   **`POST /api/job-postings/{id}/cover-letter`** — both return `201`.
   Each document is then re-validated *here*, independently of the guard run
   that happened inside the use case:
   - the fact corpus is reassembled through `ProvenanceFactAssembler`
     against the real repositories (and must now contain an `answer` fact),
   - `ProvenanceGuard().enforce(...)` is re-run over the shipped text with
     the posting's title/company/location as the only context terms: it must
     remove **nothing**, return the identical text, and still find attested
     content (criterion 2),
   - Kubernetes appears in neither document,
   - and where Kafka *does* appear, `backing_sources` includes `answer`, so
     the claim traces to what the candidate said rather than to what the
     posting asked for.

7. **ATS safety and the exports** (criterion 3):
   - the resume response's `ats_safety_violations` is empty, and
     `AtsSafetyValidator` re-run here finds nothing,
   - `exports.text` is byte-identical to the guarded content,
   - every parsed section heading is one `ats_section_headings` recognizes,
     and no section is a heading over nothing,
   - the PDF decodes to bytes starting with `%PDF` and its reported
     `pdf_byte_size` matches,
   - the cover letter is checked against the ATS rules that apply to any
     plain-text document (markdown, pipes, column whitespace, decorative
     glyphs, unrenderable characters). The heading/section rules are
     deliberately not applied to it — a letter has no section headings to
     recognize or hollow out.

8. **The exact sent versions are stored** (criterion 3):
   - `GET /api/job-postings/{id}/documents` lists both kinds at version 1
     with matching ids and `backing_sources`,
   - `GET /api/job-postings/{id}/documents/{kind}/latest` and
     `GET /api/application-documents/{id}` both return content **equal to
     what the generation call returned**, with `content_sha256` equal to a
     `hashlib.sha256` of that text computed in the test — so the snapshot is
     the sent document, not a re-derivation of it,
   - `GET /api/application-documents` returns exactly those two ids.

## What a real run produced

From the run that gated this check (synthetic candidate, real models), the
stored resume snapshot — `backing_sources: [parsed_resume, user_entered,
answer]`:

```
Dana Whitfield
...
EXPERIENCE
Senior Backend Engineer, Northwind Freight, 2021-04-01 to present
- Based in Austin, Texas
- Built Python services for shipment tracking
- Moved the billing database onto PostgreSQL
- Built and ran the Kafka event pipeline that carried shipment tracking updates for about three years, including its consumer groups and replay tooling

Backend Engineer, Harborlight Analytics, 2018-06-01 to 2021-03-01
- Maintained reporting APIs in Python and Django

EDUCATION
Bachelor of Science in Computer Science, University of Texas at Austin, completed 2018-05-01

SKILLS
- Python (7 years)
- PostgreSQL (6 years)
- Docker (5 years)
- FastAPI (3 years)
- Kafka
```

Two things worth reading off it. The Kafka line and the `Kafka` skill entry
exist only because the candidate volunteered that experience in the question
loop — before step 4 there was nothing in the system to support them.
Kubernetes, which the same posting *requires*, appears nowhere: the model was
given it as a requirement and had nothing to back it, so it did not survive.

The cover letter from the same run is short — a salutation, a sentence naming
the role, the Kafka experience, and a sign-off. That is the guard working as
designed rather than a thin letter: generic prose about the candidate that
their record does not state gets stripped, and what remains is what they can
stand behind. Note that stripped lines leave their blank neighbours in place
in a letter (`drop_empty_sections` is resume-shaped and is not applied to
prose), so a heavily-stripped letter reads as sparse rather than as a
paragraph with a hole in it.

## Cleanup

The candidate profile and the one remembered answer are deleted in a
`finally` block. The seeded job posting and the two document snapshots are
left in place deliberately — they are the artifact this check exists to
prove exists, and neither `JobPostingRepository` nor
`ApplicationDocumentRepository` exposes a delete method (a record of what
was sent must not be erasable; see `ApplicationDocument`). This is the same
convention `test_epic03_matching_pipeline.py` follows.

## Covered elsewhere, not repeated here

- **The 422 path** — `UnattestedGenerationError`, when nothing attested
  survives the guard and there is no document to return — is covered by
  `tests/application/test_generate_tailored_resume.py` and
  `tests/application/test_generate_cover_letter.py`. Provoking it here
  would mean seeding a candidate with no assertable record and spending a
  strong-tier call to watch a document fail to appear.
- **Version 2 of a document** (regenerating for the same posting after
  filling a gap) is covered by the generation, entity, and persistence tests
  (`tests/application/test_generate_tailored_resume.py`,
  `tests/domain/test_application_document.py`,
  `tests/infrastructure/test_application_document_persistence_smoke.py`);
  this check proves version 1 is stored exactly, which is the criterion.
- **Guard internals** — which terms are neutral, why requirement text never
  enters the corpus, numeric exactness — live in
  `tests/domain/test_provenance_guard.py`. This check proves the guard is
  wired into the flow that ships and that its verdict holds on real model
  output.
