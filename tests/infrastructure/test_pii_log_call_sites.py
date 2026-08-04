"""A static guard over every log call in `src/`: no PII-bearing expression
may be passed to a logger.

Why this exists alongside the runtime scrubber
----------------------------------------------
`src/infrastructure/observability/pii_redaction.py` catches personal data
that has a recognizable *shape* — an address, a phone number, a card. It
cannot catch a person's name, a street, or the text of an answer they wrote,
because those look like ordinary prose. Nothing at runtime can.

So those are kept out by never passing them to a logger, and "never" is
worth exactly as much as its enforcement. This test is the enforcement: it
parses every module under `src/`, finds each `logger.<level>(...)` call, and
fails if any argument reads a field known to carry personal data.

It is deliberately a source-level check rather than a review convention.
Adding `logger.info("filling %s", profile.full_name)` is a natural thing to
write while debugging an autofill problem, it is invisible in a diff that
also touches thirty other lines, and it puts a candidate's legal name into
every log sink the deployment has.

What it flags
-------------
Any argument expression that reads a banned name, in any of the forms this
codebase actually writes: `profile.full_name`, a bare `candidate_email`
local, `answers["email"]`, and the same inside an f-string.

The escape hatch, and why it is narrow
--------------------------------------
A `# pii-ok: <reason>` comment on any line of the call suppresses it. The
reason is mandatory — a bare `# pii-ok` does not count — because the only
legitimate uses are cases where the name is misleading (a *count* of
answers, a job posting's location rather than a candidate's) and that
argument has to be written down where the next reader will see it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

_LOG_LEVELS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
)

#: Names whose value is personal data, in any expression handed to a logger.
#:
#: Every `sensitive`-flagged ORM column is either here or in
#: `_UNMATCHABLE_SENSITIVE_COLUMNS` below — `test_every_sensitive_column_is_a_
#: decided_case` enforces that, so adding a sensitive column forces a choice
#: rather than silently widening the gap.
BANNED_NAMES: frozenset[str] = frozenset(
    {
        # Identity
        "full_name",
        "first_name",
        "last_name",
        "middle_name",
        "preferred_name",
        "candidate_name",
        # Contact
        "email",
        "candidate_email",
        "email_address",
        "phone",
        "phone_number",
        "street_address",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "zip_code",
        "date_of_birth",
        # Legal attestation / voluntary self-identification (FieldSensitivity)
        "citizenship_country",
        "visa_type",
        "work_authorization",
        "requires_sponsorship",
        "gender_identity",
        "race_ethnicity",
        "veteran_status",
        "disability_status",
        "eeo_self_identification",
        # Candidate free text and document bodies
        "answer_text",
        "question_text",
        "resume_text",
        "extracted_text",
        "cover_letter_text",
        "original_filename",
        "submission_note",
        "resolution_note",
        "raw_text",
        # A verbatim line of a generated or parsed document — a résumé line, a
        # line the provenance guard stripped. Two log sites used to write these
        # out; see `GenerationGuardAudit` and `_log_ats_findings` for why they
        # no longer do. Safe to ban as an exact name: `line_number`, `lines`
        # and `line_count` are all distinct identifiers and stay loggable.
        "line",
    }
)

#: Sensitive columns whose *name* is too common to match on statically.
#:
#: Each one names something non-sensitive somewhere else in this codebase, so
#: banning the identifier would produce false positives that get silenced with
#: `# pii-ok` until the guard means nothing:
#:
#: - `status` / `answers` / `content` / `details` — application status, an
#:   answer *count*, a document body's length, a status-change note.
#: - `location` / `city` / `country` / `state_or_region` — a job posting's
#:   location is logged legitimately; the candidate's address is the same word.
#: - `embedding` — a vector; logged as a dimension count if at all.
#:
#: These are covered by the runtime scrubber's `key=value` rule instead
#: (`postal_code=...`, `'city': '...'`), and by the fact that any *value*
#: shaped like an address or an email is redacted wherever it came from.
_UNMATCHABLE_SENSITIVE_COLUMNS: frozenset[str] = frozenset(
    {
        "answers",
        "city",
        "content",
        "country",
        "details",
        "embedding",
        "location",
        "state_or_region",
        "status",
    }
)

_ALLOW_RE = re.compile(r"#\s*pii-ok:\s*\S")


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_LEVELS:
        return False
    target = func.value
    # `logger.info(...)`, `self._logger.info(...)`, `logging.info(...)`.
    if isinstance(target, ast.Name):
        return "log" in target.id.lower()
    if isinstance(target, ast.Attribute):
        return "log" in target.attr.lower()
    return False


def _names_read(node: ast.AST) -> set[str]:
    """Every identifier-ish name an expression reads.

    Attribute accesses contribute their attribute (`profile.full_name` ->
    `full_name`), subscripts their literal string key (`d["email"]` ->
    `email`), and bare loads their own name. f-strings are walked like any
    other node, so an interpolated attribute is caught too.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
            if isinstance(child.slice.value, str):
                found.add(child.slice.value)
        elif isinstance(child, ast.keyword) and child.arg:
            found.add(child.arg)
    return found


def _suppressed(lines: list[str], node: ast.Call) -> bool:
    start = node.lineno - 1
    end = (node.end_lineno or node.lineno) - 1
    return any(_ALLOW_RE.search(line) for line in lines[start : end + 1])


def _violations() -> list[str]:
    problems: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - a parse error is a bug
            problems.append(f"{path}: could not parse ({exc})")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_log_call(node):
                continue
            if _suppressed(lines, node):
                continue
            # Every argument is scanned, including the format string — an
            # f-string leaks in that position (`logger.info(f"{p.email}")`) and
            # is the most natural way to write the mistake. String *literals*
            # are skipped instead, which is what keeps a banned word used as a
            # label ("phone=%s") from being flagged: a plain format string is a
            # Constant, and so are the literal chunks of an f-string, while its
            # interpolated expressions are not.
            arguments = [a for a in node.args if not isinstance(a, ast.Constant)]
            arguments += [
                kw.value
                for kw in node.keywords
                if not isinstance(kw.value, ast.Constant)
            ]
            for argument in arguments:
                hits = _names_read(argument) & BANNED_NAMES
                if hits:
                    problems.append(
                        f"{path.relative_to(SRC.parent)}:{argument.lineno} "
                        f"logs {sorted(hits)}"
                    )
    return problems


def test_no_log_call_passes_a_pii_bearing_expression() -> None:
    problems = _violations()
    assert not problems, (
        "PII must not be handed to a logger. Log an identifier instead, or if "
        "the name is misleading here, annotate the call with "
        "`# pii-ok: <why this is not personal data>`.\n  " + "\n  ".join(problems)
    )


def test_the_guard_actually_catches_a_planted_violation(tmp_path: Path) -> None:
    """Proves the scanner works. Without this, a guard that silently stopped
    matching anything — a renamed helper, a broken pattern — would keep
    passing forever and look like a clean codebase."""
    planted = tmp_path / "leaky.py"
    planted.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(profile):\n"
        "    logger.info('filling %s', profile.full_name)\n"
        "    logger.info(f'and {profile.phone}')\n"
        "    logger.info('answer %s', answers['answer_text'])\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_log_call(n)]
    assert len(calls) == 3

    def hits(call: ast.Call) -> set[str]:
        found: set[str] = set()
        for argument in call.args:
            if not isinstance(argument, ast.Constant):
                found |= _names_read(argument) & BANNED_NAMES
        return found

    # An argument, an f-string in the format-string position, and a dict key.
    assert hits(calls[0]) == {"full_name"}
    assert hits(calls[1]) == {"phone"}
    assert hits(calls[2]) == {"answer_text"}


def test_an_allow_comment_requires_a_reason(tmp_path: Path) -> None:
    lines_with_reason = ["logger.info('x', profile.email)  # pii-ok: it is a count"]
    lines_without = ["logger.info('x', profile.email)  # pii-ok"]
    node = ast.parse(lines_with_reason[0]).body[0].value  # type: ignore[attr-defined]
    assert _suppressed(lines_with_reason, node)
    assert not _suppressed(lines_without, node)


def test_every_sensitive_column_is_a_decided_case() -> None:
    """Ties this guard to the encryption-at-rest convention: a column flagged
    `sensitive` in `models.py` must either be a banned identifier here or be
    listed as unmatchable with a reason. Adding one forces the decision."""
    sqlalchemy = pytest.importorskip("sqlalchemy")
    assert sqlalchemy  # the import is the point; silences the unused warning
    from src.infrastructure.persistence.models import Base

    sensitive = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.info.get("sensitive")
    }
    assert sensitive, "expected models.py to flag sensitive columns"

    undecided = sensitive - BANNED_NAMES - _UNMATCHABLE_SENSITIVE_COLUMNS
    assert not undecided, (
        "These columns are flagged `sensitive` in models.py but the log guard "
        "has no position on them. Add each to BANNED_NAMES, or to "
        f"_UNMATCHABLE_SENSITIVE_COLUMNS with a reason: {sorted(undecided)}"
    )
