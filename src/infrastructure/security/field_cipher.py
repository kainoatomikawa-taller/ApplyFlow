"""FieldCipher — AES-256-GCM encryption of one field's value, self-describing
enough that a stored row says how to read itself back.

The envelope
------------
Ciphertext is stored as text, not bytes::

    encv1:<key_id>:<base64url nonce>:<base64url ciphertext+tag>

Text, because every column this replaces was already text and staying textual
keeps `psql`, backups, and Alembic's own `SELECT`/`UPDATE` statements working
without a `bytea` round-trip. Self-describing, because `key_id` is what makes
rotation possible: a reader takes the key the value names rather than assuming
the current one, so old and new ciphertext coexist in the same column (see
`EncryptionKeyring`). And versioned, because `encv1` is what a future format
change has to be able to distinguish itself from — a value with an unrecognized
prefix is refused rather than guessed at.

AES-256-GCM, so a tampered value fails loudly
---------------------------------------------
GCM authenticates as well as encrypts: flipping a byte of stored ciphertext
produces a decryption failure, not different plaintext. That matters more here
than confidentiality alone, because these fields carry legal declarations — a
work-authorization answer that silently decoded to something else is worse than
one that refuses to decode.

Purpose binding
---------------
Every value is bound, via GCM's additional authenticated data, to the
`table.column` it belongs to. So a ciphertext lifted out of
`eeo_self_identifications.disability_status` and written into
`work_authorizations.citizenship_country` will not decrypt there — the same
key, the same envelope, and still a failure. Without this, columns encrypted
under one key are interchangeable containers, and an `UPDATE ... SET a = b`
(or a mapping bug that crossed two columns) would move a candidate's answers
between meanings while every value still decrypted cleanly.

The nonce is random per encryption, so encrypting the same value twice yields
different ciphertext. That is the point — equal values must not be visibly
equal at rest — and it is also why an encrypted column cannot be queried by
value. `blind_index` exists for the one column that has to be.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from functools import lru_cache
from hashlib import sha256
from secrets import token_bytes

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.infrastructure.security.encryption_keyring import (
    EncryptionKeyring,
    get_blind_index_key,
    get_encryption_keyring,
)
from src.infrastructure.security.sensitive_access import (
    require_sensitive_data_access,
)

#: Envelope format marker. Bump only alongside a reader that still accepts the
#: previous version, or stored data becomes unreadable.
ENVELOPE_VERSION = "encv1"

#: GCM's standard nonce length. 96 bits is what the mode is specified for, and
#: random nonces at this length are safe well past any volume this stores.
_NONCE_LENGTH_BYTES = 12

#: Field separator inside the envelope. Base64url output contains no ':', and
#: key ids are validated against it (see `_KEY_ID_PATTERN` in the keyring), so
#: splitting is unambiguous.
_SEPARATOR = ":"


class FieldEncryptionError(RuntimeError):
    """Raised when a stored value cannot be decrypted.

    Covers a value that is not an envelope at all (a column that was never
    encrypted, or was overwritten by a plain `UPDATE`), one whose envelope is
    malformed, one whose authentication tag does not verify (tampering, or a
    truncating copy), and one bound to a different column than the one reading
    it.

    Deliberately one exception for all of those, and deliberately not
    recoverable-by-ignoring: the alternative to raising is returning the
    ciphertext, `None`, or a guess, and each of those puts an unreadable value
    into a domain entity that believes it holds the candidate's real answer.

    Carries `purpose` (the `table.column`) and never the value: an error
    message about a sensitive field must not quote the field.
    """

    def __init__(self, purpose: str, reason: str) -> None:
        self.purpose = purpose
        self.reason = reason
        super().__init__(
            f"Could not decrypt the stored value for '{purpose}': {reason}. "
            "The value itself is omitted from this message on purpose."
        )


class FieldCipher:
    """Encrypts and decrypts individual field values under a keyring.

    Holds no per-column state — `purpose` is passed at every call — so one
    instance serves every encrypted column in the process.
    """

    def __init__(self, keyring: EncryptionKeyring) -> None:
        self._keyring = keyring

    def encrypt(self, plaintext: str, *, purpose: str) -> str:
        """Encrypt `plaintext` for the column named by `purpose`.

        Not gated on an access scope: a caller that is writing this value
        already has it in the clear, so refusing here would protect nothing.
        Reading it back is what requires a declaration.
        """
        key_id = self._keyring.active_key_id
        nonce = token_bytes(_NONCE_LENGTH_BYTES)
        ciphertext = AESGCM(self._keyring.active_key).encrypt(
            nonce, plaintext.encode("utf-8"), _associated_data(key_id, purpose)
        )
        return _SEPARATOR.join(
            (ENVELOPE_VERSION, key_id, _b64(nonce), _b64(ciphertext))
        )

    def decrypt(self, envelope: str, *, purpose: str) -> str:
        """Decrypt a stored envelope for the column named by `purpose`.

        Requires an active sensitive-data access scope — see
        `sensitive_access`. The check is here, in the one function that turns
        ciphertext into plaintext, rather than in each of the callers that
        might forget.
        """
        require_sensitive_data_access(purpose)
        key_id, nonce, ciphertext = _parse_envelope(envelope, purpose)
        key = self._keyring.key_for(key_id)
        try:
            plaintext = AESGCM(key).decrypt(
                nonce, ciphertext, _associated_data(key_id, purpose)
            )
        except InvalidTag as exc:
            raise FieldEncryptionError(
                purpose,
                "authentication failed — the value was altered after it was "
                f"written, or it was encrypted for a different column than "
                f"'{purpose}'",
            ) from exc
        return plaintext.decode("utf-8")

    def is_encrypted(self, value: str) -> bool:
        """Whether `value` carries this module's envelope.

        For migrations and diagnostics, which legitimately need to ask
        "has this row been encrypted yet?" without attempting a decryption.
        Never used to decide whether to decrypt at read time: a column that is
        supposed to be encrypted and is not must fail, not fall back to
        returning plaintext, or a key misconfiguration would silently start
        serving (and storing) cleartext.
        """
        return value.startswith(f"{ENVELOPE_VERSION}{_SEPARATOR}")

    def blind_index(self, value: str, *, purpose: str) -> str:
        """A deterministic, keyed digest of `value` for exact-match lookup.

        The escape hatch for the one thing randomized encryption takes away:
        `WHERE email = ?`. The digest goes in its own column, is indexed, and
        is what equality queries compare against, while the value itself stays
        encrypted (see `JobApplicationModel.candidate_email_bidx`).

        It is a keyed HMAC and not a bare hash because the input spaces here
        are small and guessable — an unkeyed digest of an email address is a
        dictionary attack, not a protection. What it still leaks, unavoidably,
        is equality: two rows with the same value have the same digest, which
        is precisely the property the lookup needs. So this is for columns
        whose equality is already implied elsewhere (a candidate's own email,
        which keys their rows), never for one whose repetition is the secret.

        `purpose` is mixed in, so the same value in two columns yields two
        unrelated digests and one column's index cannot be used to probe
        another's. Requires no access scope: producing a digest reveals
        nothing, and the write path needs it as much as the read path does.
        """
        return hmac.new(
            get_blind_index_key(),
            f"{purpose}\x00{value}".encode(),
            sha256,
        ).hexdigest()


def _associated_data(key_id: str, purpose: str) -> bytes:
    """The GCM additional authenticated data: everything about this ciphertext
    that is stored in the clear and must not be swappable. Version and key id
    are included alongside the purpose so that neither can be rewritten in a
    stored envelope to steer decryption somewhere else."""
    return f"{ENVELOPE_VERSION}{_SEPARATOR}{key_id}{_SEPARATOR}{purpose}".encode()


def _parse_envelope(envelope: str, purpose: str) -> tuple[str, bytes, bytes]:
    parts = envelope.split(_SEPARATOR)
    if len(parts) != 4:
        raise FieldEncryptionError(
            purpose,
            "the stored value is not an ApplyFlow encryption envelope "
            f"(expected '{ENVELOPE_VERSION}:key_id:nonce:ciphertext')",
        )
    version, key_id, encoded_nonce, encoded_ciphertext = parts
    if version != ENVELOPE_VERSION:
        raise FieldEncryptionError(
            purpose,
            f"unsupported envelope version '{version}' (this build reads "
            f"'{ENVELOPE_VERSION}')",
        )
    try:
        nonce = _unb64(encoded_nonce)
        ciphertext = _unb64(encoded_ciphertext)
    except (binascii.Error, ValueError) as exc:
        raise FieldEncryptionError(
            purpose, "the envelope's nonce or ciphertext is not valid base64url"
        ) from exc
    if len(nonce) != _NONCE_LENGTH_BYTES:
        raise FieldEncryptionError(
            purpose,
            f"the envelope's nonce is {len(nonce)} bytes; "
            f"{_NONCE_LENGTH_BYTES} are required",
        )
    return key_id, nonce, ciphertext


def _b64(raw: bytes) -> str:
    """base64url without padding — '=' is harmless but noisy in a column."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


@lru_cache
def get_field_cipher() -> FieldCipher:
    """The process-wide cipher, built once from the configured keyring.

    Lazy (and cached) rather than a module-level instance so that importing a
    model does not require the encryption configuration to be loadable — which
    keeps `alembic`'s own imports and the unit-test suite working without a
    keyring in the environment.
    """
    return FieldCipher(get_encryption_keyring())
