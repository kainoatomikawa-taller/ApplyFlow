"""Redaction of personal data from log output.

Why a scrubber at all, when the fix is "don't log it"
-----------------------------------------------------
Call-site discipline is the primary control and it is audited (see
`tests/infrastructure/test_pii_log_call_sites.py`). This module is the
second one, and it exists because two whole classes of leak are invisible
at the call site:

* **Borrowed text.** Several log lines carry text this codebase did not
  compose — an ATS-safety violation quotes a resume line, the provenance
  guard quotes a line the model invented, an httpx error stringifies the
  request URL. Whether a candidate's email address is inside that text is
  a runtime property, so no reviewer can settle it by reading the code.
* **Tracebacks.** An exception's message and its frames' locals are
  rendered by the logging machinery, not by us.

So the rule this module enforces is: PII-shaped *values* never reach a
handler, whatever the call site asked for. `redact()` is applied to the
fully-rendered message, to the rendered traceback, and to any `extra=`
strings — see `logging_setup.install_pii_redaction`.

What it recognizes, and what it deliberately does not
-----------------------------------------------------
Redaction here is pattern-based, so it catches data with a *recognizable
shape*: email addresses, phone numbers, national ID numbers, payment card
numbers (Luhn-checked), bearer tokens and JWTs, whole URL query strings,
and `key=value` pairs whose key names a sensitive field.

It cannot catch data with no shape — a person's name, a street, a free-text
answer. "Sarah Okonkwo" is indistinguishable from "Acme Robotics" to a
regex, and a scrubber that tried would either miss most names or redact
half of every log line. Those are kept out by *not logging them*, which is
what the call-site guard enforces and what the audit in
`docs/decisions/0003-pii-out-of-logs-and-urls.md` records.

What it *can* do about shapeless data is act on the label: a value written
as `full_name=Jane Doe` or `'street_address': '17 Bellwether Lane'` is
redacted because the key names a sensitive field, whatever the value looks
like. That covers the common accident — a whole DTO or `dict` reaching a log
line through `%r` — but not a bare `logger.info("filling %s", name)`, where
nothing in the text says what the value is. Hence the call-site guard.

The known cost of the label rule: an unquoted value runs across spaces until
the next `key=`, so prose following one gets redacted along with it
(`app_key=s3cret failed` loses the "failed"). Over-redacting a word beats
under-redacting an address, and quoted and comma-delimited values — which is
what reprs and this codebase's own log lines produce — are unaffected.

IP addresses are also left alone. They are personal data under GDPR, but in
this application the addresses that show up in logs belong to outbound ATS
and LLM hosts rather than to the candidate, and redacting them would cost
the diagnostic value of the retry/backoff logging without protecting
anybody. If a request-logging middleware is ever added, that decision has
to be revisited — and that is precisely the reason it is written down here.

Failing safe
------------
Every pattern replaces the *value* and keeps its label, so a redacted line
still says what kind of thing was there (`email=[redacted:email]`). When in
doubt the choice is always to over-redact: `token=` is scrubbed even when
the token is an ATS pagination cursor, because a lost cursor in a log line
costs a debugging session and a leaked credential costs more.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Callable, Iterable
from typing import Final

#: The marker left behind, parameterized by what was removed. Callers grep
#: for `[redacted:` when checking whether a pipeline is scrubbing at all.
_MARK: Final = "[redacted:{kind}]"


def _mark(kind: str) -> str:
    return _MARK.format(kind=kind)


# ---- Key names that make a value sensitive whatever it looks like ----------
#
# Kept in sync with the `sensitive`-flagged ORM columns (see
# `models.py::_SENSITIVE_COLUMN_INFO`) plus the credential names this app
# passes to third parties. Matching is case-insensitive throughout.
#
# The split between the two tuples is about false positives, and it is load
# bearing. These names appear *only* in personal-data contexts, so they are
# matched anywhere inside a key: `email` covers `candidate_email` and
# `email_address` alike, and there is no plausible key containing "email"
# whose value is safe to log.
_WILDCARD_KEY_NAMES: Final[tuple[str, ...]] = (
    # Identity and contact
    "full_name",
    "first_name",
    "last_name",
    "middle_name",
    "preferred_name",
    "candidate_name",
    "email",
    "e_mail",
    "phone",
    "telephone",
    "street_address",
    "address_line",
    "postal_code",
    "zip_code",
    "date_of_birth",
    # Legal attestation and voluntary self-identification (FieldSensitivity)
    "citizenship_country",
    "visa_type",
    "work_authorization",
    "requires_sponsorship",
    "sponsorship_required",
    "gender_identity",
    "race_ethnicity",
    "veteran_status",
    "disability_status",
    # Candidate free text and document bodies
    "answer_text",
    "question_text",
    "resume_text",
    "extracted_text",
    "cover_letter_text",
    "original_filename",
    "submission_note",
    "resolution_note",
)

# These are ordinary English words that occur inside keys naming perfectly
# loggable things — `cache_read_input_tokens` is telemetry this codebase logs
# on purpose, and wildcard-matching "token" would redact it and destroy the
# LLM cost logging. So a key here has to *end* with the word, optionally
# behind a snake_case prefix: `token`, `access_token` and `app_key` match,
# while `input_tokens` and `keyword` do not.
_SUFFIX_KEY_NAMES: Final[tuple[str, ...]] = (
    "dob",
    "eeo",
    "mobile",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "app_key",
    "app_id",
    "access_key",
    "authorization",
    "credential",
)


def _alternation(names: tuple[str, ...]) -> str:
    """Longest-first, so `app_key` wins over `key` in a shared prefix."""
    return "|".join(sorted(names, key=len, reverse=True))


_SENSITIVE_KEY_PATTERN: Final = (
    r"\w*(?:" + _alternation(_WILDCARD_KEY_NAMES) + r")\w*"
    r"|"
    r"(?:\w+_)?(?:" + _alternation(_SUFFIX_KEY_NAMES) + r")"
)

# Matches `email=jane@x.com`, `"phone": "+1 555 010 9999"`, `app_key => abc`.
#
# Two value shapes, because both occur: a quoted string (a `dict` or dataclass
# repr, as in `{'app_key': 'shhh'}`) and a bare token (the `key=value` prose
# the log lines in this codebase are written in).
#
# A quoted value runs to its closing quote. A bare one runs to the first
# structural delimiter — comma, semicolon, closing bracket — and then keeps
# going across spaces, because `street_address=17 Bellwether Lane` is a whole
# address and stopping at the first space would leave most of it behind. What
# stops the run is the next `key=`, so `access_token=abc secret=xyz` is still
# two separate redactions rather than one that swallows both.
#
# The cost is that trailing prose after a bare sensitive value is redacted
# with it. That is the right direction to err, and it is why the value-shape
# rules run *before* this one (see `_RULES`): a phone number or an address
# with its own recognizable shape is already gone by the time this runs, so
# this rule only has to handle values that have no shape at all.
_KEY_VALUE_RE: Final = re.compile(
    r"(?P<key>\b(?:" + _SENSITIVE_KEY_PATTERN + r")\b)"
    r"(?P<keyclose>['\"]?)"
    r"(?P<sep>\s*(?:=>|[=:])\s*)"
    r"(?:"
    r"(?P<quote>['\"])(?P<quoted>(?:[^'\"\\]|\\.)*)(?P=quote)"
    r"|"
    r"(?P<bare>[^\s'\"&,;)\]}]+"
    r"(?:[ \t]+(?![\w.\-]+\s*(?:=>|[=:]))[^\s'\"&,;)\]}]+)*"
    r")"
    r")",
    re.IGNORECASE,
)

# A whole query string goes, not just its sensitive keys: `?q=` on the search
# API carries profile-derived keywords, and Adzuna requires its `app_key` in
# the query because its API takes no header. Keeping the scheme, host and
# path preserves everything the retry/backoff logs are actually for.
_URL_QUERY_RE: Final = re.compile(
    r"(?P<prefix>\b(?:https?|wss?)://[^\s?#'\"<>]*)\?[^\s#'\"<>]*",
    re.IGNORECASE,
)

_EMAIL_RE: Final = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)

# US-style national ID. Distinctive enough to match on its own.
_NATIONAL_ID_RE: Final = re.compile(r"(?<![\w\-])\d{3}-\d{2}-\d{4}(?![\w\-])")

# Two shapes only, both unambiguous: a `+` international number, or the
# 3-3-4 grouping with real separators. A bare 10-digit run is *not* matched —
# it is indistinguishable from the internal identifiers this app logs on
# purpose, and redacting those would blind the tracker logs.
_PHONE_RE: Final = re.compile(
    r"(?<![\w.])"
    r"(?:"
    r"\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,4}){2,4}"
    r"|"
    r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"
    r")"
    r"(?![\w.]|\d)"
)

# `eyJ...` is a base64url-encoded `{"` — every JWT header starts this way.
_JWT_RE: Final = re.compile(
    r"\beyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]*)?"
)

_BEARER_RE: Final = re.compile(
    r"\b(?P<scheme>bearer|basic)\s+[A-Za-z0-9._\-~+/]+=*", re.IGNORECASE
)

# Candidate payment-card runs, confirmed by Luhn before being replaced. The
# check is what makes this safe to apply: a 13-digit epoch-milliseconds
# timestamp or a long internal counter would otherwise be redacted.
_CARD_CANDIDATE_RE: Final = re.compile(r"(?<![\w.])(?:\d[ \-]?){12,18}\d(?![\w.]|\d)")


def _passes_luhn(digits: str) -> bool:
    """Whether `digits` satisfies the Luhn checksum used by payment cards."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _redact_card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"[^\d]", "", raw)
    if not 13 <= len(digits) <= 19 or not _passes_luhn(digits):
        return raw
    return _mark("card")


def _redact_key_value(match: re.Match[str]) -> str:
    quote = match.group("quote")
    value = match.group("quoted") if quote is not None else match.group("bare")
    # Leaving an already-redacted value alone is what makes `redact` idempotent
    # across the record factory and the formatter, which both run it.
    if value.startswith("[redacted:"):
        return match.group(0)
    wrap = quote or ""
    return (
        f"{match.group('key')}{match.group('keyclose')}{match.group('sep')}"
        f"{wrap}{_mark('value')}{wrap}"
    )


def _redact_bearer(match: re.Match[str]) -> str:
    return f"{match.group('scheme')} {_mark('credential')}"


def _redact_url_query(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}?{_mark('query')}"


# Order is deliberate, and each position earns its place.
#
# The URL rule is first, so a query string collapses whole rather than leaving
# `?app_key=[redacted:value]&what=...` behind.
#
# The value-shape rules come next, ahead of the structural `key=value` rule.
# That ordering is what lets `key=value` consume unquoted multi-word values
# safely: by the time it runs, anything with a recognizable shape has already
# been replaced by a marker, so `phone=+1 (555) 010-9999` is already
# `phone=[redacted:phone]` and the greedy bare-value branch never sees it.
# Reversing the two would have `key=value` stop at the first space and leave
# `010-9999` in the line.
#
# `key=value` is therefore last, as the catch-all for values that have no
# shape at all — a name, a street, an answer — recognized only by what they
# were labelled.
#: A replacement is either a literal marker or a function, because some rules
#: have to inspect the match before deciding (Luhn on a card, which capture
#: group held the value, whether the text is already redacted).
_Replacement = str | Callable[[re.Match[str]], str]

_RULES: Final[tuple[tuple[re.Pattern[str], _Replacement], ...]] = (
    (_URL_QUERY_RE, _redact_url_query),
    (_JWT_RE, _mark("credential")),
    (_BEARER_RE, _redact_bearer),
    (_NATIONAL_ID_RE, _mark("national_id")),
    (_EMAIL_RE, _mark("email")),
    (_CARD_CANDIDATE_RE, _redact_card),
    (_PHONE_RE, _mark("phone")),
    (_KEY_VALUE_RE, _redact_key_value),
)


def redact(text: str) -> str:
    """Return `text` with every recognizable personal or secret value replaced.

    Idempotent: the markers it writes contain nothing any rule matches, so
    re-redacting already-redacted text is a no-op. That matters because both
    the record factory and the formatter run this, and a record that passes
    through two handlers is redacted twice.
    """
    if not text:
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


# ---- Attaching redaction to the logging machinery -------------------------

#: Attributes `logging.LogRecord.__init__` sets. Anything else on a record
#: arrived through `extra=`, is therefore application-supplied, and gets
#: scrubbed like the message.
_STANDARD_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    vars(
        logging.LogRecord(
            name="",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
    )
) | {"message", "asctime", "taskName"}


def redact_record(record: logging.LogRecord) -> logging.LogRecord:
    """Scrub `record` in place and return it.

    Renders the message eagerly (`msg % args`) and replaces `msg` with the
    redacted result, clearing `args`. Lazy `%`-formatting is given up on
    purpose: a rule has to see the interpolated text to catch an email that
    arrived as an argument, and this application logs at a volume where the
    formatting cost is irrelevant.

    The traceback is rendered here too, into `exc_text`. `logging.Formatter`
    reuses a populated `exc_text` instead of re-rendering, so the redacted
    version is what gets emitted. `exc_info` itself is left in place for
    handlers that want the live exception object — which is why
    `configure_logging` also installs `PiiRedactingFormatter`, so a formatter
    that ignores `exc_text` still cannot emit an unredacted frame.
    """
    try:
        rendered = record.getMessage()
    except Exception:  # noqa: BLE001 - a broken format string must not lose the log
        rendered = f"{record.msg!r} % {record.args!r}"
    record.msg = redact(rendered)
    record.args = None

    if record.exc_info and not record.exc_text:
        record.exc_text = redact(
            "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
        )
    elif record.exc_text:
        record.exc_text = redact(record.exc_text)

    if record.stack_info:
        record.stack_info = redact(record.stack_info)

    for key, value in list(vars(record).items()):
        if key not in _STANDARD_RECORD_ATTRS and isinstance(value, str):
            setattr(record, key, redact(value))

    return record


class PiiRedactingFilter(logging.Filter):
    """Scrubs records on their way into a handler.

    The record factory installed by `install_pii_redaction` already covers
    every record created through the `logging` API, so this is for handlers
    that are handed records built some other way — `makeLogRecord` from a
    queue or a socket, which is how multiprocess log shipping works.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        redact_record(record)
        return True


class PiiRedactingFormatter(logging.Formatter):
    """Redacts the fully-formatted line, including the traceback.

    The last line of defence: whatever a handler, a format string, or a
    third-party formatter subclass assembled, this sees the exact bytes about
    to be written and scrubs them.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingFormatterProxy(logging.Formatter):
    """Wraps a formatter a handler already had, and redacts what it produces.

    Wrapping rather than rebuilding, because the formatters this retrofits
    belong to other people: uvicorn's is a `ColourizedFormatter` and Celery's
    understands task ids. Reconstructing a plain `logging.Formatter` from the
    original's format string would silently drop that behaviour, and reading
    the format string back out means touching private attributes to begin
    with. Delegating keeps whatever they do and only adds the scrub.
    """

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))


def redacting_formatters(handlers: Iterable[logging.Handler]) -> None:
    """Ensure every handler's formatter redacts, preserving what it did before.

    Used to retrofit handlers this application did not install — uvicorn and
    Celery both configure their own. Idempotent: a handler already wrapped, or
    already using `PiiRedactingFormatter`, is left alone.
    """
    for handler in handlers:
        existing = handler.formatter
        if isinstance(existing, PiiRedactingFormatter | RedactingFormatterProxy):
            continue
        if existing is None:
            handler.setFormatter(PiiRedactingFormatter())
            continue
        handler.setFormatter(RedactingFormatterProxy(existing))
