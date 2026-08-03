"""Cryptographic and access-control mechanisms for sensitive data at rest.

Three pieces, deliberately separate:

- `encryption_keyring` — where the keys come from (the Epic 00 config layer,
  never source code) and which one signs new writes.
- `field_cipher` — how a single field's value becomes ciphertext and back.
- `sensitive_access` — *who* is allowed to turn ciphertext back into
  plaintext, and the gate that refuses when nobody has said.

The persistence-layer adapter that wires all three onto actual columns is
`src/infrastructure/persistence/encrypted_types.py`.
"""
