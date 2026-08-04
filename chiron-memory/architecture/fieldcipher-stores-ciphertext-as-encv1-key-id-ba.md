---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-23
type: architecture
title: FieldCipher stores ciphertext as `encv1:<key_id>:<base64url nonce>:<base64url…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/security/field_cipher.py
---
FieldCipher stores ciphertext as `encv1:<key_id>:<base64url nonce>:<base64url ciphertext>` using AES-256-GCM, with the envelope version + key id + column purpose bound into the AAD.

## Why
a self-describing envelope lets a stored row say how to read itself back, and binding purpose into AAD prevents ciphertext from one column being decrypted as if it were another.

## Where
src/infrastructure/security/field_cipher.py
