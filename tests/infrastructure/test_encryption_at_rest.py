"""Encryption at rest: the gate that refuses, and the properties the cipher
promises.

Eight persistence smoke tests point at this file — "see `test_encryption_at_rest.py`
for the tests that assert the refusal when no scope is open" — and until the
Epic 07 hardening pass it did not exist. Those smoke tests all open an access
scope, so they prove decryption *works*; nothing proved it *stops*. A gate that
was accidentally disabled (a scope opened at import time, a `require_` call
dropped from the decrypt path) would have left the entire suite green.

Needs no database. Everything here works on the cipher and the column types
directly, which is the level the guarantees live at: `FieldCipher.decrypt` is the
one function that turns ciphertext into plaintext, and the column types are the
one place the ORM touches it.

Deliberately **does not** request the shared `sensitive_access` fixture at module
scope. Most tests here are about what happens with no scope in effect, and an
autouse scope would quietly turn the control off for the whole file — the exact
reason `tests/conftest.py` says that fixture must be asked for by name.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from src.infrastructure.config import ConfigurationError, Settings
from src.infrastructure.persistence.encrypted_types import (
    EncryptedBoolean,
    EncryptedJson,
    EncryptedString,
)
from src.infrastructure.security.encryption_keyring import (
    DEVELOPMENT_KEY_ID,
    KEY_LENGTH_BYTES,
    EncryptionKeyring,
    UnknownEncryptionKeyError,
)
from src.infrastructure.security.field_cipher import (
    ENVELOPE_VERSION,
    FieldCipher,
    FieldEncryptionError,
    get_field_cipher,
)
from src.infrastructure.security.sensitive_access import (
    SensitiveAccessDeniedError,
    SensitiveDataAccess,
    current_sensitive_data_access,
    sensitive_data_access,
)

_PURPOSE = "user_profiles.full_name"
_OTHER_PURPOSE = "eeo_self_identifications.disability_status"
_SECRET = "Sarah Okonkwo"


def _keyring(*key_ids: str) -> EncryptionKeyring:
    """A keyring with distinct, deterministic keys. Active key first, matching
    the configuration format's own convention.

    Each key is derived from its *id* rather than from its position, so that
    `_keyring("a")` and `_keyring("b", "a")` agree about what key "a" is. That
    is what the rotation test needs: it encrypts under one keyring and decrypts
    under a later one, which is only a rotation if the retired key is the same
    bytes in both.
    """
    keys = {
        key_id: hashlib.sha256(f"test-key/{key_id}".encode()).digest()
        for key_id in key_ids
    }
    assert all(len(key) == KEY_LENGTH_BYTES for key in keys.values())
    return EncryptionKeyring(keys=keys, active_key_id=key_ids[0])


def _cipher(*key_ids: str) -> FieldCipher:
    return FieldCipher(_keyring(*key_ids or ("k1",)))


# -- The gate -----------------------------------------------------------------


def test_no_scope_is_open_by_default_in_this_suite() -> None:
    """The premise every other test in this file rests on. If something in the
    suite ever opened a process-wide scope, the refusal tests below would pass
    for the wrong reason — so the premise is asserted rather than assumed."""
    assert current_sensitive_data_access() is None


def test_decrypting_without_an_access_scope_is_refused() -> None:
    cipher = _cipher()
    envelope = cipher.encrypt(_SECRET, purpose=_PURPOSE)

    with pytest.raises(SensitiveAccessDeniedError) as excinfo:
        cipher.decrypt(envelope, purpose=_PURPOSE)

    # The message names the column, which is the fastest route to the offending
    # query, and points at the module that lists the authorized paths.
    assert _PURPOSE in str(excinfo.value)
    assert "sensitive_data_access" in str(excinfo.value)
    assert excinfo.value.purpose == _PURPOSE


def test_the_refusal_does_not_quote_the_value_it_refused() -> None:
    """An error about a sensitive field must not put the field in the log line
    that reports it."""
    cipher = _cipher()
    envelope = cipher.encrypt(_SECRET, purpose=_PURPOSE)
    with pytest.raises(SensitiveAccessDeniedError) as excinfo:
        cipher.decrypt(envelope, purpose=_PURPOSE)
    assert _SECRET not in str(excinfo.value)


def test_decrypting_inside_a_scope_returns_the_plaintext(
    sensitive_access: SensitiveDataAccess,
) -> None:
    cipher = _cipher()
    envelope = cipher.encrypt(_SECRET, purpose=_PURPOSE)
    assert cipher.decrypt(envelope, purpose=_PURPOSE) == _SECRET


def test_encrypting_needs_no_scope() -> None:
    """A write path already holds the plaintext it is storing, so gating it
    would be theatre — and would make the gate something every write had to
    route around, which is how gates get switched off."""
    assert current_sensitive_data_access() is None
    assert _cipher().encrypt(_SECRET, purpose=_PURPOSE)


def test_the_scope_closes_when_its_block_exits() -> None:
    """A scope that outlived its block would turn the first authorized request in
    a process into a permanent grant."""
    cipher = _cipher()
    envelope = cipher.encrypt(_SECRET, purpose=_PURPOSE)
    with sensitive_data_access(subject="s", reason="r"):
        assert cipher.decrypt(envelope, purpose=_PURPOSE) == _SECRET
    with pytest.raises(SensitiveAccessDeniedError):
        cipher.decrypt(envelope, purpose=_PURPOSE)


def test_a_nested_scope_restores_the_outer_one_rather_than_clearing_it() -> None:
    """A task that opens a scope and calls into code that opens another must not
    come back with no scope at all — that would make the caller's own remaining
    reads fail depending on what it happened to call."""
    with sensitive_data_access(subject="outer", reason="r") as outer:
        with sensitive_data_access(subject="inner", reason="r"):
            assert current_sensitive_data_access() is not None
            assert current_sensitive_data_access().subject == "inner"  # type: ignore[union-attr]
        assert current_sensitive_data_access() == outer


def test_a_scope_must_name_a_subject_and_a_reason() -> None:
    """An anonymous scope would defeat the point of the call sites being the
    reviewable artifact."""
    with pytest.raises(ValueError):
        SensitiveDataAccess(subject="  ", reason="r")
    with pytest.raises(ValueError):
        SensitiveDataAccess(subject="s", reason="  ")


# -- The gate, through the ORM column types -----------------------------------
#
# The layer the smoke tests actually exercise. `process_result_value` is what
# SQLAlchemy calls on load, so this is the same code path a repository read takes
# — without needing a database for it.


def test_loading_an_encrypted_column_without_a_scope_is_refused() -> None:
    column = EncryptedString(_PURPOSE)
    stored = column.process_bind_param(_SECRET, None)

    with pytest.raises(SensitiveAccessDeniedError):
        column.process_result_value(stored, None)


def test_loading_an_encrypted_column_inside_a_scope_returns_the_value(
    sensitive_access: SensitiveDataAccess,
) -> None:
    column = EncryptedString(_PURPOSE)
    stored = column.process_bind_param(_SECRET, None)
    assert stored != _SECRET
    assert column.process_result_value(stored, None) == _SECRET


def test_null_stays_null_through_a_column_round_trip(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """A nullable encrypted column means "the candidate did not provide this".
    Encrypting the absence would make "no answer" indistinguishable from "an
    answer" at rest — and for `eeo_self_identifications`, "declined" is itself
    one of the answers, so that distinction is the whole disclosure boundary."""
    column = EncryptedString("user_profiles.phone")
    assert column.process_bind_param(None, None) is None
    assert column.process_result_value(None, None) is None


def test_a_boolean_column_round_trips_as_a_boolean(
    sensitive_access: SensitiveDataAccess,
) -> None:
    column = EncryptedBoolean("work_authorizations.requires_sponsorship")
    for value in (True, False):
        stored = column.process_bind_param(value, None)
        loaded = column.process_result_value(stored, None)
        assert loaded is value, "False must survive as False, never as None"


def test_a_boolean_is_stored_with_the_spelling_postgres_casts_to() -> None:
    """Migration 0021 turned these columns into text with `USING column::text`
    and then encrypted what was there, so the encrypted form of an existing
    `true` has to be the string this class writes for `True`. Any other spelling
    and every pre-migration row decrypts to something the column rejects.

    Asserted on the plaintext *inside* the envelope, because that is the byte
    sequence the migration's correctness depends on.
    """
    column = EncryptedBoolean("work_authorizations.requires_sponsorship")
    cipher = get_field_cipher()
    purpose = "work_authorizations.requires_sponsorship"
    with sensitive_data_access(subject="test", reason="assert stored spelling"):
        assert (
            cipher.decrypt(column.process_bind_param(True, None), purpose=purpose)
            == "true"
        )
        assert (
            cipher.decrypt(column.process_bind_param(False, None), purpose=purpose)
            == "false"
        )


def test_a_json_column_round_trips_and_is_stored_compactly(
    sensitive_access: SensitiveDataAccess,
) -> None:
    column = EncryptedJson("answer_memories.embedding")
    value = [0.5, 0.25, 0.125]
    stored = column.process_bind_param(value, None)
    assert column.process_result_value(stored, None) == value
    plaintext = get_field_cipher().decrypt(stored, purpose="answer_memories.embedding")
    assert plaintext == json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_a_column_rejects_a_value_of_the_wrong_python_type() -> None:
    """Coercing would store a repr, and the repr would decrypt cleanly — so
    nothing downstream would ever notice."""
    with pytest.raises(TypeError):
        EncryptedString(_PURPOSE).process_bind_param(42, None)
    with pytest.raises(TypeError):
        EncryptedBoolean("work_authorizations.requires_sponsorship").process_bind_param(
            "yes", None
        )


# -- Confidentiality and integrity properties --------------------------------


def test_the_same_value_encrypts_differently_every_time() -> None:
    """Equal values must not be visibly equal at rest. This is also why an
    encrypted column cannot be queried by value."""
    cipher = _cipher()
    first = cipher.encrypt(_SECRET, purpose=_PURPOSE)
    second = cipher.encrypt(_SECRET, purpose=_PURPOSE)
    assert first != second


def test_the_stored_envelope_does_not_contain_the_plaintext() -> None:
    envelope = _cipher().encrypt(_SECRET, purpose=_PURPOSE)
    assert _SECRET not in envelope
    assert base64.b64encode(_SECRET.encode()).decode().rstrip("=") not in envelope


def test_the_envelope_names_its_version_and_key_but_not_its_contents() -> None:
    """Both are needed in the clear — the version so a format change can be
    distinguished, the key id so rotation works — and neither is a secret."""
    envelope = _cipher("2026-08").encrypt(_SECRET, purpose=_PURPOSE)
    version, key_id, nonce, ciphertext = envelope.split(":")
    assert version == ENVELOPE_VERSION
    assert key_id == "2026-08"
    assert nonce and ciphertext


def test_a_tampered_value_fails_instead_of_decoding_to_something_else(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """GCM authenticates as well as encrypts, and that matters more here than
    confidentiality alone: these columns carry legal declarations, and a
    work-authorization answer that silently decoded to something else is worse
    than one that refuses to decode."""
    cipher = _cipher()
    version, key_id, nonce, ciphertext = cipher.encrypt(
        _SECRET, purpose=_PURPOSE
    ).split(":")
    flipped = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]

    with pytest.raises(FieldEncryptionError) as excinfo:
        cipher.decrypt(":".join((version, key_id, nonce, flipped)), purpose=_PURPOSE)
    assert "authentication failed" in str(excinfo.value)
    assert _SECRET not in str(excinfo.value)


def test_a_value_moved_to_another_column_will_not_decrypt_there(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """The purpose binding, and the reason it exists: without it, columns
    encrypted under one key are interchangeable containers, and an
    `UPDATE ... SET a = b` — or a mapping bug that crossed two columns — would
    move a candidate's answers between meanings while every value still
    decrypted cleanly."""
    cipher = _cipher()
    envelope = cipher.encrypt("Yes", purpose=_OTHER_PURPOSE)
    with pytest.raises(FieldEncryptionError):
        cipher.decrypt(envelope, purpose=_PURPOSE)


def test_rewriting_the_purpose_inside_a_stored_envelope_does_not_help() -> None:
    """The purpose is not stored in the envelope, so there is nothing to
    rewrite — but the version and key id *are*, and they are authenticated too,
    so neither can be edited to steer decryption somewhere else."""
    cipher = _cipher("k1", "k2")
    with sensitive_data_access(subject="test", reason="tamper check"):
        version, key_id, nonce, ciphertext = cipher.encrypt(
            _SECRET, purpose=_PURPOSE
        ).split(":")
        # Same keyring, a key it really holds, and still refused: the key id is
        # part of the authenticated data.
        with pytest.raises(FieldEncryptionError):
            cipher.decrypt(
                ":".join((version, "k2", nonce, ciphertext)), purpose=_PURPOSE
            )


def test_plaintext_left_in_an_encrypted_column_raises_rather_than_passing_through(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """The single most important failure mode to get right. A column that is
    supposed to be encrypted and is not — a missed migration, a manual `UPDATE`,
    a `server_default` — must fail. Falling back to returning the value would
    make a key misconfiguration silently start serving, and then storing,
    cleartext."""
    with pytest.raises(FieldEncryptionError) as excinfo:
        _cipher().decrypt("Sarah Okonkwo", purpose=_PURPOSE)
    assert "not an ApplyFlow encryption envelope" in str(excinfo.value)

    column = EncryptedString(_PURPOSE)
    with pytest.raises(FieldEncryptionError):
        column.process_result_value("Sarah Okonkwo", None)


def test_an_unrecognized_envelope_version_is_refused_rather_than_guessed_at(
    sensitive_access: SensitiveDataAccess,
) -> None:
    cipher = _cipher()
    _, key_id, nonce, ciphertext = cipher.encrypt(_SECRET, purpose=_PURPOSE).split(":")
    with pytest.raises(FieldEncryptionError) as excinfo:
        cipher.decrypt(
            ":".join(("encv99", key_id, nonce, ciphertext)), purpose=_PURPOSE
        )
    assert "unsupported envelope version" in str(excinfo.value)


def test_a_truncated_nonce_is_refused(sensitive_access: SensitiveDataAccess) -> None:
    cipher = _cipher()
    version, key_id, nonce, ciphertext = cipher.encrypt(
        _SECRET, purpose=_PURPOSE
    ).split(":")
    with pytest.raises(FieldEncryptionError) as excinfo:
        cipher.decrypt(
            ":".join((version, key_id, nonce[:4], ciphertext)), purpose=_PURPOSE
        )
    assert "nonce" in str(excinfo.value)


# -- Key rotation -------------------------------------------------------------


def test_a_value_written_under_a_retired_key_still_reads(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """The whole point of the keyring: rotation without a rewrite-the-world
    migration. Old ciphertext keeps naming the old key and stays readable while
    that key is still configured."""
    old = _cipher("2026-02")
    envelope = old.encrypt(_SECRET, purpose=_PURPOSE)

    # A later deployment: new key active, old one still held.
    rotated = FieldCipher(_keyring("2026-08", "2026-02"))
    assert rotated.decrypt(envelope, purpose=_PURPOSE) == _SECRET
    # And new writes go under the new key.
    assert rotated.encrypt(_SECRET, purpose=_PURPOSE).split(":")[1] == "2026-08"


def test_a_value_naming_a_key_that_is_no_longer_configured_says_so(
    sensitive_access: SensitiveDataAccess,
) -> None:
    """A configuration problem wearing a data problem's clothes. Naming the
    missing key is what sends someone to the deployment rather than hunting a
    corruption bug."""
    envelope = _cipher("2026-02").encrypt(_SECRET, purpose=_PURPOSE)
    with pytest.raises(UnknownEncryptionKeyError) as excinfo:
        FieldCipher(_keyring("2026-08")).decrypt(envelope, purpose=_PURPOSE)
    assert "2026-02" in str(excinfo.value)
    assert excinfo.value.key_id == "2026-02"


def test_a_keyring_whose_active_key_is_absent_is_refused() -> None:
    """Nothing could decrypt what it writes."""
    with pytest.raises(ConfigurationError):
        EncryptionKeyring(keys={"k1": b"\x01" * KEY_LENGTH_BYTES}, active_key_id="k2")


def test_a_short_key_is_refused_rather_than_stretched() -> None:
    """A 16-byte key silently accepted would mean a column believed to be
    AES-256-encrypted is not."""
    short = base64.b64encode(b"\x01" * 16).decode()
    with pytest.raises(ConfigurationError) as excinfo:
        EncryptionKeyring.from_configuration_value(f"k1:{short}")
    assert "AES-256" in str(excinfo.value)


def test_the_first_configured_key_is_the_active_one() -> None:
    keys = ",".join(
        f"{key_id}:{base64.b64encode(bytes((index + 1,)) * KEY_LENGTH_BYTES).decode()}"
        for index, key_id in enumerate(("2026-08", "2026-02"))
    )
    keyring = EncryptionKeyring.from_configuration_value(keys)
    assert keyring.active_key_id == "2026-08"
    assert set(keyring.keys) == {"2026-08", "2026-02"}


def test_a_duplicate_key_id_is_refused() -> None:
    encoded = base64.b64encode(b"\x01" * KEY_LENGTH_BYTES).decode()
    with pytest.raises(ConfigurationError):
        EncryptionKeyring.from_configuration_value(f"k1:{encoded},k1:{encoded}")


# -- The development fallback -------------------------------------------------


def test_the_development_key_is_identifiable_in_every_row_it_writes() -> None:
    """It is a key committed to this repository, so it is worthless as
    protection. What it must be is *visible*: a production row encrypted under
    it should be obvious from a `SELECT`."""
    keyring = EncryptionKeyring.for_development()
    assert keyring.active_key_id == DEVELOPMENT_KEY_ID
    assert "insecure" in DEVELOPMENT_KEY_ID
    assert keyring.is_development_fallback

    envelope = FieldCipher(keyring).encrypt(_SECRET, purpose=_PURPOSE)
    assert envelope.split(":")[1] == DEVELOPMENT_KEY_ID


def test_a_real_keyring_is_not_reported_as_the_development_fallback() -> None:
    assert not _keyring("2026-08").is_development_fallback
    assert not _keyring(DEVELOPMENT_KEY_ID, "2026-08").is_development_fallback


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_the_development_fallback_is_refused_outside_development(
    environment: str,
) -> None:
    """The guard that keeps a real candidate's citizenship and EEO answers from
    being encrypted under a key that is in this repository — worse than not
    booting, and invisible afterwards."""
    with pytest.raises(ValueError) as excinfo:
        Settings(
            environment=environment,
            openai_api_key="x",
            anthropic_api_key="x",
            supabase_jwt_secret="x",
            field_encryption_keys="",
            field_blind_index_key="x",
        )
    assert "FIELD_ENCRYPTION_KEYS" in str(excinfo.value)


def test_the_blind_index_key_is_also_required_outside_development() -> None:
    with pytest.raises(ValueError) as excinfo:
        Settings(
            environment="production",
            openai_api_key="x",
            anthropic_api_key="x",
            supabase_jwt_secret="x",
            field_encryption_keys="k1:" + base64.b64encode(b"\x01" * 32).decode(),
            field_blind_index_key="",
        )
    assert "FIELD_BLIND_INDEX_KEY" in str(excinfo.value)


# -- The blind index ----------------------------------------------------------


def test_the_blind_index_is_deterministic_so_a_lookup_can_match() -> None:
    cipher = get_field_cipher()
    purpose = "job_applications.candidate_email"
    assert cipher.blind_index("a@b.com", purpose=purpose) == cipher.blind_index(
        "a@b.com", purpose=purpose
    )


def test_the_blind_index_needs_no_access_scope() -> None:
    """Producing a digest reveals nothing, and the write path needs it as much
    as the read path does."""
    assert current_sensitive_data_access() is None
    assert get_field_cipher().blind_index("a@b.com", purpose="x.y")


def test_the_blind_index_does_not_contain_the_value() -> None:
    digest = get_field_cipher().blind_index("sarah@example.com", purpose="x.y")
    assert "sarah" not in digest
    assert "example" not in digest
    assert len(digest) == 64, "hex sha256"


def test_one_columns_blind_index_cannot_probe_another() -> None:
    """`purpose` is mixed in, so the same value in two columns yields two
    unrelated digests."""
    cipher = get_field_cipher()
    assert cipher.blind_index("a@b.com", purpose="one.col") != cipher.blind_index(
        "a@b.com", purpose="two.col"
    )


def test_the_blind_index_is_keyed_rather_than_a_bare_hash() -> None:
    """The input spaces here are small and guessable — an unkeyed digest of an
    email address is a dictionary attack, not a protection. Verified by showing
    the digest is not the plain sha256 of anything an attacker could assemble
    without the key."""
    value = "sarah@example.com"
    purpose = "job_applications.candidate_email"
    digest = get_field_cipher().blind_index(value, purpose=purpose)
    for guess in (
        value,
        f"{purpose}\x00{value}",
        f"{purpose}:{value}",
    ):
        assert digest != hashlib.sha256(guess.encode()).hexdigest()
