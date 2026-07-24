"""add requirements column to job_postings

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("requirements", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "requirements")
