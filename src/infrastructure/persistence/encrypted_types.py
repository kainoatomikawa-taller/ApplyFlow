"""Column types that encrypt on the way into the database and decrypt on the
way out — the adapter between `security/field_cipher.py` and the ORM.

Why at the column type and not in the repositories
--------------------------------------------------
The alternative is for each repository's `_to_model`/`_to_entity` to call the
cipher by hand. That was rejected for one reason: it can be forgotten. Every
repository is a place where a new column can be mapped, and a column mapped
without the encryption call is a column that silently stores plaintext, with
nothing failing. Declaring the *column* as encrypted moves the decision to the
schema, where the column is defined exactly once, and lets a single test walk
`Base.metadata` and assert that every sensitive-flagged column has an encrypted
type (see `tests/infrastructure/test_sensitive_column_coverage.py`). Repositories
then need no changes at all — they read and write the Python values they always
did.

The trade-off is that these columns can no longer be filtered, sorted, or
grouped by in SQL. That is inherent to encryption at rest rather than a
limitation of this approach: the database is holding ciphertext, so it cannot
compare values. Where an equality lookup is genuinely required, a blind-index
column carries a keyed digest for the database to compare instead (see
`FieldCipher.blind_index`).

Storage shape
-------------
All three types store `Text`, whatever their Python value: ciphertext has no
fixed length and no useful type. That means the column loses its former SQL
type — `Boolean`, `JSON`, `String(32)` — as a constraint. The Python-side type
is still enforced, by these classes on the way in and on the way out, so a
`bool` column still round-trips as `bool`; what is gone is the database's own
ability to reject a bad value. Accepted deliberately: a check constraint the
database cannot evaluate is not worth keeping a queryable plaintext column for.

`cache_ok = False` because each instance carries its own `purpose`, which
participates in the ciphertext. Letting SQLAlchemy treat two differently-bound
instances as one cache entry is exactly the kind of subtle mix-up the purpose
binding exists to catch, so the compiled-statement cache is opted out of.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Dialect, Text
from sqlalchemy.types import TypeDecorator

from src.infrastructure.security.field_cipher import (
    FieldEncryptionError,
    get_field_cipher,
)


class _EncryptedColumn(TypeDecorator[Any]):
    """Shared machinery: encrypt on bind, decrypt on load, NULL passes through.

    NULL is stored as NULL rather than as encrypted emptiness. It has to be:
    the nullable columns here mean "the candidate did not provide this", the
    repositories map that to `None`, and turning it into a ciphertext blob
    would make "no answer" indistinguishable from "an answer" at rest — which
    is the opposite of what a column holding an EEO response wants. The
    presence of a row is already visible; the absence of a value stays visible
    too.
    """

    impl = Text
    cache_ok = False

    def __init__(self, purpose: str) -> None:
        """`purpose` is the `table.column` this instance encrypts for, and it
        is authenticated into every value (see `FieldCipher`). Passed
        explicitly rather than read from the column at mapping time because it
        must be stable and reviewable: it is part of the stored format, so a
        rename that changed it would strand existing rows, and a literal string
        in the model is something a diff can show.
        """
        super().__init__()
        if not purpose.strip():
            raise ValueError(
                "An encrypted column needs a non-empty purpose (use "
                "'table_name.column_name')."
            )
        self.purpose = purpose

    def process_bind_param(self, value: Any | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return get_field_cipher().encrypt(self._to_text(value), purpose=self.purpose)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> Any | None:
        if value is None:
            return None
        plaintext = get_field_cipher().decrypt(value, purpose=self.purpose)
        return self._from_text(plaintext)

    def _to_text(self, value: Any) -> str:
        raise NotImplementedError

    def _from_text(self, plaintext: str) -> Any:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.purpose!r})"


class EncryptedString(_EncryptedColumn):
    """A text value, encrypted. Rejects non-strings at the boundary rather than
    coercing: `str(value)` on something unexpected would store a repr, and the
    repr would decrypt cleanly, so nothing downstream would ever notice."""

    def _to_text(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{self.purpose} is an encrypted text column and was given "
                f"{type(value).__name__}."
            )
        return value

    def _from_text(self, plaintext: str) -> str:
        return plaintext


class EncryptedBoolean(_EncryptedColumn):
    """A boolean, encrypted as the literal text Postgres' own `boolean::text`
    produces.

    Matching that spelling is not cosmetic: migration 0021 changes these
    columns to text with `USING column::text` and then encrypts what is there,
    so the encrypted form of an existing `true` has to be the same string this
    class would have written for `True`. Anything else and rows written before
    the migration would decrypt to a value this class does not recognize.
    """

    _TRUE = "true"
    _FALSE = "false"

    def _to_text(self, value: Any) -> str:
        if not isinstance(value, bool):
            raise TypeError(
                f"{self.purpose} is an encrypted boolean column and was given "
                f"{type(value).__name__}."
            )
        return self._TRUE if value else self._FALSE

    def _from_text(self, plaintext: str) -> bool:
        if plaintext == self._TRUE:
            return True
        if plaintext == self._FALSE:
            return False
        raise FieldEncryptionError(
            self.purpose,
            "the decrypted value is not a stored boolean (expected "
            f"'{self._TRUE}' or '{self._FALSE}')",
        )


class EncryptedJson(_EncryptedColumn):
    """A JSON-serializable value, encrypted as its compact JSON text.

    Replaces a `JSON` column, so the database can no longer index into or
    query the structure. Nothing did: the JSON columns encrypted here
    (`application_reviews.answers`, `answer_memories.embedding`) are read whole
    by the repository that owns them and never filtered on in SQL.

    `sort_keys=True` keeps the serialization stable for a given value, which
    makes a re-encryption of unchanged data a no-op in content terms even
    though the ciphertext differs. `separators` drops the whitespace `json`
    adds by default — every byte here is a byte that gets encrypted.
    """

    def _to_text(self, value: Any) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{self.purpose} is an encrypted JSON column and was given a "
                f"value that is not JSON-serializable: {type(value).__name__}."
            ) from exc

    def _from_text(self, plaintext: str) -> Any:
        try:
            return json.loads(plaintext)
        except ValueError as exc:
            raise FieldEncryptionError(
                self.purpose, "the decrypted value is not valid JSON"
            ) from exc
