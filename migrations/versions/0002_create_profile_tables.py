"""create profile tables (user_profiles, work_history, education, skills)

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("headline", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_profiles_user_id", "user_profiles", ["user_id"], unique=True
    )

    op.create_table(
        "work_history_entries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_work_history_entries_profile_id",
        "work_history_entries",
        ["profile_id"],
    )

    op.create_table(
        "education_entries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("institution_name", sa.String(length=255), nullable=False),
        sa.Column("degree", sa.String(length=255), nullable=False),
        sa.Column("field_of_study", sa.String(length=255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_education_entries_profile_id",
        "education_entries",
        ["profile_id"],
    )

    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("proficiency", sa.String(length=32), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
    )
    op.create_index("ix_skills_profile_id", "skills", ["profile_id"])
    op.create_unique_constraint(
        "uq_skills_profile_id_name", "skills", ["profile_id", "name"]
    )


def downgrade() -> None:
    op.drop_table("skills")
    op.drop_index("ix_education_entries_profile_id", table_name="education_entries")
    op.drop_table("education_entries")
    op.drop_index(
        "ix_work_history_entries_profile_id", table_name="work_history_entries"
    )
    op.drop_table("work_history_entries")
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_table("user_profiles")
