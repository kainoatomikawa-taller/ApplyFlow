"""create job_applications table

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("candidate_email", sa.String(length=320), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("role_title", sa.String(length=255), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("match_score", sa.Integer(), nullable=True),
        sa.Column("tailored_cover_letter", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_job_applications_candidate_email",
        "job_applications",
        ["candidate_email"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_applications_candidate_email", table_name="job_applications"
    )
    op.drop_table("job_applications")
