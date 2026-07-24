"""add staleness fields to job_postings

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
    )
    op.add_column(
        "job_postings",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_postings",
        sa.Column(
            "consecutive_link_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index("ix_job_postings_status", "job_postings", ["status"])
    op.create_index(
        "ix_job_postings_status_last_checked_at",
        "job_postings",
        ["status", "last_checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_postings_status_last_checked_at", table_name="job_postings")
    op.drop_index("ix_job_postings_status", table_name="job_postings")
    op.drop_column("job_postings", "consecutive_link_failures")
    op.drop_column("job_postings", "last_checked_at")
    op.drop_column("job_postings", "status")
