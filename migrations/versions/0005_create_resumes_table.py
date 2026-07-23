"""create resumes table

Revision ID: 0005
Revises: 0004
Create Date: 2024-01-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors the comments in src/infrastructure/persistence/models.py.
_PII_COMMENT = "May contain PII — never log."


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "original_filename",
            sa.String(length=255),
            nullable=False,
            comment=_PII_COMMENT,
        ),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False, comment=_PII_COMMENT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_unique_constraint(
        "uq_resumes_storage_key", "resumes", ["storage_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")
