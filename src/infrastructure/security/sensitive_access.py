"""The gate that decides whether ciphertext may become plaintext.

Encryption at rest without this is half a control. A key loaded into the
process decrypts for everything in the process: a sweep task that joins across
profiles, a debugging script someone runs against production, a new endpoint
written by someone who did not know these columns were special. All of them get
candidate citizenship and EEO answers in the clear, and none of them had to ask.

So decryption here is *declared*, never incidental. An access path states who
it is acting for and why, by entering `sensitive_data_access(...)`; the
encrypted column types (`persistence/encrypted_types.py`) refuse to decrypt
outside that scope. Encryption is deliberately not gated — a write path already
holds the plaintext it is storing, so requiring a declaration to protect it
would be theatre.

What counts as an authorized access path
----------------------------------------
Exactly the places that have established, by their own means, who they are
acting for:

- `interfaces/http/dependencies.get_current_user` — a verified bearer token has
  named the user, and the scope lasts the request.
- The Celery task entry points that load a candidate's own records
  (`infrastructure/tasks/analysis_tasks.py`), scoped to the subject whose work
  the task was queued for.
- The CLI, for the local operator running a command against their own data.

That list is short on purpose, and it is the reviewable artifact: grep for
`sensitive_data_access(` and you have every path in this codebase that can read
this data. Adding a scope is a deliberate act with a `reason` attached to it, so
widening access is visible in a diff rather than implied by an import.

What this is not
----------------
It is not authorization. It does not check that `subject` may see the row being
loaded — row ownership is enforced where it always was, by repositories and use
cases filtering on `user_id`. This gate answers a different question ("is
anything at all allowed to decrypt right now?"), and the two compose: an
authenticated request that queries someone else's row still gets nothing,
because the query never matches.

It is also not a defence against code running inside this process that wants
plaintext badly enough to open its own scope. Nothing at this layer could be.
The threat it addresses is the far more common one — plaintext reaching a
caller that never intended to read it, and nobody noticing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

#: The scope in effect for the current task/thread, if any. A context variable
#: rather than a parameter threaded through every call because the consumer is a
#: SQLAlchemy type decorator: it is handed one column value and nothing else, so
#: there is no argument to pass. `contextvars` (not thread-locals) because the
#: API is asyncio — each request task gets its own copy, and a scope opened in
#: one cannot leak into another.
_active_access: ContextVar[SensitiveDataAccess | None] = ContextVar(
    "applyflow_sensitive_data_access", default=None
)


@dataclass(frozen=True)
class SensitiveDataAccess:
    """A declaration that decrypting sensitive fields is intended right now.

    `subject` is who the access is on behalf of — a `user_id` for a request or
    a task, or a `local-operator`-style label for the CLI. `reason` is short
    free text naming the operation, so an audit of this file's call sites reads
    as a list of purposes rather than a list of `True`s.

    Both are required and non-empty: a scope worth opening is a scope worth
    saying something about, and an anonymous one would defeat the point of the
    call sites being the reviewable artifact.
    """

    subject: str
    reason: str

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError(
                "A sensitive-data access scope must name the subject it acts "
                "for; an unattributed scope is not reviewable."
            )
        if not self.reason.strip():
            raise ValueError(
                "A sensitive-data access scope must state its reason; that "
                "text is what makes the call site auditable."
            )


class SensitiveAccessDeniedError(RuntimeError):
    """Raised when something tried to decrypt a sensitive field with no access
    scope in effect.

    A programming error rather than a runtime condition, which is why it is a
    `RuntimeError` and not an application-layer exception mapped to a 403: the
    caller is code, not a user, and the fix is to declare the access (or to
    stop reading the column) rather than to hand the request different
    credentials. Surfacing it as a 500 is correct — a path that reads this data
    without having said so is broken, and quietly returning ciphertext or `None`
    instead would turn that into a data-corruption bug somewhere further away.

    Carries the purpose (`table.column`) so the message names the column that
    was refused, which is the fastest route to the offending query.
    """

    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        super().__init__(
            f"Refusing to decrypt '{purpose}': no sensitive-data access scope "
            "is in effect. Wrap the access path in "
            "`sensitive_data_access(subject=..., reason=...)` — see "
            "src/infrastructure/security/sensitive_access.py for which paths "
            "are authorized to do that."
        )


@contextmanager
def sensitive_data_access(
    *, subject: str, reason: str
) -> Iterator[SensitiveDataAccess]:
    """Permit decryption of sensitive fields for the duration of the block.

    Nests: an inner scope replaces the outer one and the outer one is restored
    on exit, so a task that opens a scope and calls into code that opens
    another does not end up with the inner subject still in effect afterwards.
    """
    access = SensitiveDataAccess(subject=subject, reason=reason)
    token = _active_access.set(access)
    try:
        yield access
    finally:
        _active_access.reset(token)


def current_sensitive_data_access() -> SensitiveDataAccess | None:
    """The scope in effect, or None. For tests and diagnostics — the
    encryption path uses `require_sensitive_data_access` so that a missing
    scope cannot be handled by ignoring it."""
    return _active_access.get()


def require_sensitive_data_access(purpose: str) -> SensitiveDataAccess:
    """The scope in effect, or raise. Called by every decryption."""
    access = _active_access.get()
    if access is None:
        raise SensitiveAccessDeniedError(purpose)
    return access
