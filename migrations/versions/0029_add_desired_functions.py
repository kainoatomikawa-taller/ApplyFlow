"""Add the candidate's desired job functions to user_profiles.

Function — the kind of work — rather than industry, because it is the axis a
candidate states readily ("I want to do product", "I want quant finance") and the
axis a posting's text actually reveals: a description says what you would be doing
in every paragraph and names the employer's sector once, in the boilerplate.

Industry is a second, independent axis and is deliberately deferred. The column is
named `desired_functions` rather than something vaguer so that adding industry
later is an addition rather than a rename of a column that already holds a
candidate's answers.

Same shape and reasoning as `desired_employment_types` in 0027: a nullable JSON
array of enum values, nothing queries an individual element, and
`JSON(none_as_null=True)` on the model keeps "not stated" as SQL NULL rather than
the JSON literal `null` (see 0026 for what that defect cost).

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles", sa.Column("desired_functions", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "desired_functions")
