"""Add the candidate's job-search preferences to user_profiles.

The first columns on this table that record a *want* rather than a fact. Every
other field describes the candidate and is compared against what a posting
demands; these describe the search and are compared against what a posting is
(see `JobSearchPreferences` and `JobSearchPreferenceFilter`).

No `*_source` column to go with them, unlike `address_source`/`links_source`. A
provenance tag answers "who says this is true about you, and may we assert it to
an employer" — nothing here is ever asserted to anyone, and a preference cannot
be parsed off a résumé, so a source column would carry no information.

Nullable with no server default: NULL and `[]` would both have to mean "not
stated", and one representation is better than two. The model declares
`JSON(none_as_null=True)` so an empty preference set stores as SQL NULL rather
than the JSON literal `null` — see migration 0026 for what that defect cost.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("desired_employment_types", sa.JSON(), nullable=True),
    )
    op.add_column("user_profiles", sa.Column("desired_terms", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "desired_terms")
    op.drop_column("user_profiles", "desired_employment_types")
