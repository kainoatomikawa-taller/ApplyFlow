"""replace resolved_listings with resolved_company_boards

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("resolved_listings")
    op.create_table(
        "resolved_company_boards",
        sa.Column("normalized_company", sa.String(length=255), primary_key=True),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("board_token", sa.String(length=255), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("resolved_company_boards")
    op.create_table(
        "resolved_listings",
        sa.Column("normalized_company", sa.String(length=255), primary_key=True),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("apply_url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
    )
