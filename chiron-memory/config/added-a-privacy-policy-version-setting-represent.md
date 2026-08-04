---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-10
type: config
title: Added a `PRIVACY_POLICY_VERSION` setting representing the version of the privacy/consent…
tags: [config]
created: 2026-08-04
resource: src/infrastructure/config.py, .env.example, migrations/versions/0022_create_consent_decisions.py.
---
Added a `PRIVACY_POLICY_VERSION` setting representing the version of the privacy/consent notice shown to users; each recorded consent decision stores the policy_version in effect at the time it was made

## Where
src/infrastructure/config.py, .env.example, migrations/versions/0022_create_consent_decisions.py.
