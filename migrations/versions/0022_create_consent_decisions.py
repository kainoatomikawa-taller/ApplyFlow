"""create consent_decisions table

The consent ledger: one row per decision a user made about one purpose, appended
and never rewritten. See `ConsentDecisionModel` for the column-level contract and
`ConsentDecision` for why a ledger rather than a boolean per purpose — GDPR Art.
7(1) puts the burden on the controller to *demonstrate* that consent was given,
and a column that gets overwritten on withdrawal destroys the one fact that
matters afterwards.

The decisions worth reading before changing anything here:

- The primary key is (user_id, purpose, sequence) with no surrogate id, mirroring
  `application_status_events`. A decision has no identity beyond the ledger it
  belongs to and its position in it, `sequence` is 0-based and gap-free so the
  key doubles as the ordering, and appending the same entry twice is a constraint
  violation rather than a duplicated row.
- No foreign key to `user_profiles`. A consent decision is about the account, not
  the profile: it has to be recordable before a profile exists — accepting a
  notice is the first thing a new user does — and readable after the profile is
  erased, which is the whole point of the table.
- Nothing here is encrypted, and that is load-bearing rather than an oversight. A
  purpose, a yes/no, a timestamp and a notice version describe a *decision about*
  personal data without containing any, which is what lets this table stay
  queryable and what makes retaining it past an erasure request defensible
  instead of a hole in the erasure.

No backfill. A ledger with no entries is a real and correct state — the user has
not been asked — and every purpose has a defined answer in that state (consent
purposes are denied, contract-based ones permitted; see
`ConsentPurpose.granted_by_default`). Inventing a grant for the existing account
would fabricate the exact record this table exists to make trustworthy.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consent_decisions",
        sa.Column("user_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "purpose",
            sa.String(length=64),
            primary_key=True,
            nullable=False,
            comment=(
                "What was decided about: account_and_applications | "
                "ai_document_generation | answer_reuse | "
                "sensitive_attribute_storage | automated_portal_interaction. "
                "See src/domain/value_objects/consent_purpose.py."
            ),
        ),
        # 0-based and gap-free, so the primary key doubles as the ordering: two
        # decisions recorded in the same clock tick still have a definite order,
        # which decided_at alone could not give them.
        sa.Column("sequence", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "policy_version",
            sa.String(length=32),
            nullable=False,
            comment=(
                "The privacy-notice version this decision was made against — "
                "what makes the consent demonstrably informed (GDPR Art. 7(1))."
            ),
        ),
        comment=(
            "Append-only consent ledger. Deliberately retained after an erasure "
            "request as the record that the erasure was lawful — see the "
            "'consents' category in "
            "src/domain/services/personal_data_inventory.py."
        ),
    )
    # One user's whole ledger, in order: the read behind every consent screen and
    # every data export. The primary key already serves the per-purpose read.
    op.create_index(
        "ix_consent_decisions_user_id_decided_at",
        "consent_decisions",
        ["user_id", "decided_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consent_decisions_user_id_decided_at", table_name="consent_decisions"
    )
    op.drop_table("consent_decisions")
