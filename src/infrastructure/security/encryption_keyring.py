"""EncryptionKeyring — the keys that encrypt sensitive fields at rest, read
from the Epic 00 config layer and never from source code.

Why a keyring and not a key
---------------------------
A single key cannot be rotated. Every ciphertext this codebase writes names
the key that produced it (see `field_cipher`'s envelope), so a keyring holding
several keys at once lets a rotation happen without a rewrite-the-world
migration: the new key goes at the front and signs every new write, the old
ones stay behind it and are still accepted on read. Rows re-encrypt under the
active key whenever they are next written, and a retired key is removed from
the configuration once nothing decrypts under it any more.

Configuration format
--------------------
`FIELD_ENCRYPTION_KEYS` is a comma-separated list of `key_id:base64_key`
pairs, **most recent first**::

    FIELD_ENCRYPTION_KEYS=2026-08:PmJ...=,2026-02:1Qz...=

The first entry is the active key — the one new writes use. There is
deliberately no second "which key is active" setting: two settings that have
to agree are two settings that can disagree, and the failure mode of
disagreeing (writing under a key id whose bytes are missing) is data that
cannot be read back.

Each key is 32 raw bytes (AES-256), base64-encoded. Generate one with::

    openssl rand -base64 32

Key ids are opaque labels, not secrets — they travel in the clear inside
every envelope so a reader knows which key to reach for. Dates are a good
choice because "which key is older" is the question rotation asks.

The blind-index key is separate
-------------------------------
`FIELD_BLIND_INDEX_KEY` keys the deterministic lookup digest that lets an
encrypted column still be searched by exact value (see
`FieldCipher.blind_index`). It is *not* part of the rotating keyring, because
rotating it changes every digest it ever produced and so invalidates every
stored index value at once. Rotating it is a data migration — recompute every
blind-index column — which is exactly why it does not ride along with the
routine key rotation above.

Development
-----------
With nothing configured, `for_development()` supplies a keyring whose key is
derived from a constant in this file. That key is worthless as protection —
it is in the repository — and it exists only so a fresh clone can run the test
suite and a local stack without ceremony. `Settings` refuses an empty
configuration outside `development` (see `config.py`), and the key id says what
it is (`dev-insecure`) in every envelope it writes, so a production row
encrypted under it would be visible as such at a glance.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from src.infrastructure.config import ConfigurationError, Settings, get_settings

#: AES-256. Rejected rather than stretched: a 16-byte key silently accepted
#: here would mean a column believed to be AES-256-encrypted is not.
KEY_LENGTH_BYTES = 32

#: Key ids travel in the clear inside every envelope and are parsed back out of
#: it, so they may not contain the envelope's own separator. Restricted further
#: than strictly necessary so an id is always safe to put in a log line.
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: The key id every development-fallback envelope is stamped with. Named to be
#: unmistakable in a `SELECT` against a database that should not have it.
DEVELOPMENT_KEY_ID = "dev-insecure"

#: Derived, rather than a base64 blob pasted here, only so nothing in this file
#: can be mistaken for a real key that leaked into source control.
_DEVELOPMENT_KEY_MATERIAL = (
    "applyflow-development-only-field-encryption-key-do-not-use-in-production"
)


@dataclass(frozen=True)
class EncryptionKeyring:
    """The keys available for encrypting and decrypting sensitive fields.

    `active_key_id` names the key new writes use; `keys` holds every key that
    may still appear in stored ciphertext, including the active one.
    """

    keys: Mapping[str, bytes]
    active_key_id: str

    def __post_init__(self) -> None:
        if not self.keys:
            raise ConfigurationError(
                "An EncryptionKeyring needs at least one key. Set "
                "FIELD_ENCRYPTION_KEYS (see src/infrastructure/security/"
                "encryption_keyring.py for the format)."
            )
        if self.active_key_id not in self.keys:
            raise ConfigurationError(
                f"The active key id '{self.active_key_id}' is not one of the "
                "configured keys, so nothing could decrypt what it writes."
            )
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))

    @property
    def active_key(self) -> bytes:
        """The key new ciphertext is written under."""
        return self.keys[self.active_key_id]

    def key_for(self, key_id: str) -> bytes:
        """The key a stored envelope names.

        Raises `UnknownEncryptionKeyError` rather than returning None: a row
        naming a key this process does not hold is un-readable, and the useful
        response is to say which key is missing so it can be put back into the
        configuration. Silently treating it as corrupt would send someone
        hunting a data bug instead of a deployment one.
        """
        try:
            return self.keys[key_id]
        except KeyError:
            raise UnknownEncryptionKeyError(key_id, tuple(self.keys)) from None

    @property
    def is_development_fallback(self) -> bool:
        """Whether this keyring is the in-repository development key.

        Checked by tests and by the configuration guard; nothing in the
        encryption path branches on it, because the cipher's behavior must not
        depend on which key it holds.
        """
        return tuple(self.keys) == (DEVELOPMENT_KEY_ID,)

    @classmethod
    def from_settings(cls, settings: Settings) -> EncryptionKeyring:
        """Build the keyring from configuration, falling back to the
        development key only when nothing is configured.

        The fallback is safe to leave unconditional here because `Settings`
        has already refused an empty `FIELD_ENCRYPTION_KEYS` outside
        `development` — the two guards sit in the layers that own their halves:
        config decides what is acceptable for an environment, this module
        decides how the bytes are read.
        """
        configured = settings.field_encryption_keys.get_secret_value().strip()
        if not configured:
            return cls.for_development()
        return cls.from_configuration_value(configured)

    @classmethod
    def from_configuration_value(cls, value: str) -> EncryptionKeyring:
        """Parse `key_id:base64_key[,key_id:base64_key...]`, active key first."""
        keys: dict[str, bytes] = {}
        order: list[str] = []
        for entry in (part.strip() for part in value.split(",")):
            if not entry:
                continue
            key_id, separator, encoded = entry.partition(":")
            if not separator:
                raise ConfigurationError(
                    "FIELD_ENCRYPTION_KEYS entries must be "
                    f"'key_id:base64_key'; got '{key_id}' with no ':'."
                )
            key_id = key_id.strip()
            if not _KEY_ID_PATTERN.match(key_id):
                raise ConfigurationError(
                    f"'{key_id}' is not a usable key id. Use 1-64 characters "
                    "from A-Z a-z 0-9 . _ - (it is stored alongside every "
                    "encrypted value)."
                )
            if key_id in keys:
                raise ConfigurationError(
                    f"Key id '{key_id}' appears twice in FIELD_ENCRYPTION_KEYS; "
                    "an id must name exactly one key."
                )
            keys[key_id] = _decode_key(key_id, encoded.strip())
            order.append(key_id)

        if not order:
            raise ConfigurationError(
                "FIELD_ENCRYPTION_KEYS is set but contains no key entries."
            )
        return cls(keys=keys, active_key_id=order[0])

    @classmethod
    def for_development(cls) -> EncryptionKeyring:
        """The in-repository development key. See this module's docstring."""
        key = hashlib.sha256(_DEVELOPMENT_KEY_MATERIAL.encode("utf-8")).digest()
        return cls(keys={DEVELOPMENT_KEY_ID: key}, active_key_id=DEVELOPMENT_KEY_ID)


class UnknownEncryptionKeyError(ConfigurationError):
    """Raised when stored ciphertext names a key this process does not hold.

    A configuration problem wearing a data problem's clothes: the row is
    intact, the key it needs was retired (or was never deployed here). Carries
    the missing id and the ids that *are* loaded, since that pair is what
    identifies the mistake — and neither is secret.
    """

    def __init__(self, key_id: str, available_key_ids: tuple[str, ...]) -> None:
        self.key_id = key_id
        self.available_key_ids = available_key_ids
        loaded = ", ".join(available_key_ids) or "none"
        super().__init__(
            f"No encryption key with id '{key_id}' is loaded, so a value "
            f"encrypted under it cannot be read. Loaded key ids: {loaded}. Add "
            "the key back to FIELD_ENCRYPTION_KEYS."
        )


def _decode_key(key_id: str, encoded: str) -> bytes:
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConfigurationError(
            f"The key for id '{key_id}' is not valid base64. Generate one with "
            "`openssl rand -base64 32`."
        ) from exc
    if len(key) != KEY_LENGTH_BYTES:
        raise ConfigurationError(
            f"The key for id '{key_id}' decodes to {len(key)} bytes; "
            f"{KEY_LENGTH_BYTES} are required for AES-256. Generate one with "
            "`openssl rand -base64 32`."
        )
    return key


def _decode_blind_index_key(settings: Settings) -> bytes:
    configured = settings.field_blind_index_key.get_secret_value().strip()
    if not configured:
        # Same reasoning as the keyring's development fallback, and gated by
        # the same `Settings` validator outside development. Derived from a
        # different constant so a dev database's digests do not double as a
        # dictionary against its ciphertext.
        return hashlib.sha256(
            f"{_DEVELOPMENT_KEY_MATERIAL}/blind-index".encode()
        ).digest()
    return _decode_key("FIELD_BLIND_INDEX_KEY", configured)


@lru_cache
def get_encryption_keyring() -> EncryptionKeyring:
    """The process-wide keyring, built once from `get_settings()`."""
    return EncryptionKeyring.from_settings(get_settings())


@lru_cache
def get_blind_index_key() -> bytes:
    """The process-wide blind-index key, built once from `get_settings()`."""
    return _decode_blind_index_key(get_settings())
