---
id: 644dfa30-a7db-462f-a43d-4999b3597642-0
type: architecture
title: Encryption-at-rest lives in a new src/infrastructure/security/ module
tags: [architecture]
created: 2026-08-03
resource: src/infrastructure/security/{encryption_keyring,field_cipher,sensitive_access}.py
---
Encryption-at-rest lives in a new src/infrastructure/security/ module: EncryptionKeyring (rotation-capable, keys sourced only from config), FieldCipher (AES-256-GCM, versioned self-describing envelope with purpose binding), and a sensitive_data_access gate/context-manager.

## Learned
decryption must be explicitly scoped via sensitive_data_access(...) before use — it is not automatic on read.

## Where
src/infrastructure/security/{encryption_keyring,field_cipher,sensitive_access}.py
