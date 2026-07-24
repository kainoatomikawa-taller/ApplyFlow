"""add clearance_level and highest_degree columns to user_profiles

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("clearance_level", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("highest_degree", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "highest_degree")
    op.drop_column("user_profiles", "clearance_level")
