"""create job_match_feedback table

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_match_feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "job_posting_id",
            sa.String(length=64),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("score_at_feedback", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_job_match_feedback_user_id", "job_match_feedback", ["user_id"]
    )
    op.create_index(
        "ix_job_match_feedback_job_posting_id",
        "job_match_feedback",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_job_match_feedback_created_at", "job_match_feedback", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_match_feedback_created_at", table_name="job_match_feedback"
    )
    op.drop_index(
        "ix_job_match_feedback_job_posting_id", table_name="job_match_feedback"
    )
    op.drop_index("ix_job_match_feedback_user_id", table_name="job_match_feedback")
    op.drop_table("job_match_feedback")
