"""Add the candidate's current education standing to user_profiles.

The gap this closes
-------------------
`highest_degree` means highest *completed* degree, and that was the only thing the
profile could say about education level. A current undergraduate therefore had no
honest answer available: "high school" is true and disqualifies them from most
new-grad roles and many internships (where "bachelor's required" means *in
progress*), "bachelor's" gets the right postings and is false, and leaving it
unset turns degree filtering off so Master's-only roles keep appearing.

These three columns add the missing fact — what the candidate is currently doing —
so `HardDisqualifierFilter` can count an in-progress degree towards a stated
degree requirement, except where the posting demands `GRADUATED`.

Plain columns rather than JSON, unlike the preferences added in 0027: each is a
single scalar, and `expected_graduation` is a real date that a "graduating before
this term" query would want to compare on.

Nullable with no server default. NULL means "not stated", which is deliberately
distinct from a stored `not_enrolled` — the first is a candidate who has not
answered, the second is one who has, and eligibility filtering only applies to the
second (see `EducationStanding.is_stated`).

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("enrollment_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("degree_in_progress", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_profiles", sa.Column("expected_graduation", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "expected_graduation")
    op.drop_column("user_profiles", "degree_in_progress")
    op.drop_column("user_profiles", "enrollment_status")
