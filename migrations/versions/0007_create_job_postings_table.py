"""create job_postings table

Revision ID: 0007
Revises: 0006
Create Date: 2024-01-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column(
            "is_remote", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("apply_url", sa.String(length=2048), nullable=False),
        sa.Column("salary", sa.JSON(), nullable=True),
        sa.Column("posted_at", sa.Date(), nullable=True),
        sa.Column("normalized_company", sa.String(length=255), nullable=False),
        sa.Column("normalized_title", sa.String(length=255), nullable=False),
        sa.Column("normalized_location", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_postings_source", "job_postings", ["source"])
    op.create_index(
        "ix_job_postings_normalized_company", "job_postings", ["normalized_company"]
    )
    op.create_index(
        "ix_job_postings_normalized_title", "job_postings", ["normalized_title"]
    )
    op.create_index(
        "ix_job_postings_normalized_location", "job_postings", ["normalized_location"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_postings_normalized_location", table_name="job_postings"
    )
    op.drop_index("ix_job_postings_normalized_title", table_name="job_postings")
    op.drop_index("ix_job_postings_normalized_company", table_name="job_postings")
    op.drop_index("ix_job_postings_source", table_name="job_postings")
    op.drop_table("job_postings")
