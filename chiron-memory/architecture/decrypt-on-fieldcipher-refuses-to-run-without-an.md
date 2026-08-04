---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-24
type: architecture
title: `decrypt()` on FieldCipher refuses to run without an active sensitive-data access scope,…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/security/field_cipher.py, src/infrastructure/persistence/encrypted_types.py
---
`decrypt()` on FieldCipher refuses to run without an active sensitive-data access scope, and the refusal error does not quote the ciphertext/value.

## Why
this is the enforcement point that keeps decrypted PII from leaking through logs/errors when no legitimate access scope is open; verified via mutation testing (removing the gate fails test_encryption_at_rest.py).

## Where
src/infrastructure/security/field_cipher.py, src/infrastructure/persistence/encrypted_types.py
