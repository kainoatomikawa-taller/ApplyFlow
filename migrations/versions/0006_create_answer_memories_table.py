"""create answer_memories table

Revision ID: 0006
Revises: 0005
Create Date: 2024-01-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors the comments in src/infrastructure/persistence/models.py.
_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."
_PROVENANCE_COMMENT = (
    "Fact provenance: parsed_resume | user_entered | answer. "
    "Required — see src/domain/value_objects/provenance_source.py."
)


def upgrade() -> None:
    op.create_table(
        "answer_memories",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "question_text", sa.Text(), nullable=False, comment=_SENSITIVE_COMMENT
        ),
        sa.Column(
            "answer_text", sa.Text(), nullable=False, comment=_SENSITIVE_COMMENT
        ),
        sa.Column(
            "embedding", sa.JSON(), nullable=False, comment=_SENSITIVE_COMMENT
        ),
        sa.Column(
            "source", sa.String(length=16), nullable=False, comment=_PROVENANCE_COMMENT
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_answer_memories_user_id", "answer_memories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_answer_memories_user_id", table_name="answer_memories")
    op.drop_table("answer_memories")
