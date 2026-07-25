"""add submission_key to tracked_applications

What it is for: logging a submitted application has to be idempotent, and the
only way to make that reliable is a constraint. A service that reads "is it
already logged?" and then inserts can be run twice concurrently — a
double-clicked submit button is exactly that — and both reads can miss. The
unique index below is what refuses the second write; the logger catches the
violation and returns the row that won.

Added in three steps rather than as a NOT NULL column outright, so the
migration is correct whether or not `tracked_applications` already has rows:
add it nullable, backfill each existing row with its own id (unique by
construction, and honest — those rows predate submission-event tracking), then
tighten to NOT NULL.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tracked_applications",
        sa.Column(
            "submission_key",
            sa.String(length=128),
            nullable=True,
            comment=(
                "The submission event this row was logged from (in practice "
                "the submitted review's id). Unique per candidate — this is "
                "the idempotency guarantee for submission logging."
            ),
        ),
    )
    # Backfill: any pre-existing row was logged before submission events were
    # tracked, and its own id is the only value guaranteed unique per user.
    op.execute(
        "UPDATE tracked_applications SET submission_key = id "
        "WHERE submission_key IS NULL"
    )
    op.alter_column(
        "tracked_applications",
        "submission_key",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_tracked_applications_submission_key",
        "tracked_applications",
        ["user_id", "submission_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_tracked_applications_submission_key",
        "tracked_applications",
        type_="unique",
    )
    op.drop_column("tracked_applications", "submission_key")
