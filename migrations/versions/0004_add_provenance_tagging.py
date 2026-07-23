"""add provenance tagging to every stored fact

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors `_PROVENANCE_COMMENT` in src/infrastructure/persistence/models.py.
_PROVENANCE_COMMENT = (
    "Fact provenance: parsed_resume | user_entered | answer. "
    "Required — see src/domain/value_objects/provenance_source.py."
)


def upgrade() -> None:
    # One fact per row in these tables — source is always required.
    for table in (
        "work_history_entries",
        "education_entries",
        "skills",
        "work_authorizations",
        "eeo_self_identifications",
    ):
        op.add_column(
            table,
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                comment=_PROVENANCE_COMMENT,
            ),
        )

    # user_profiles bundles several scalar facts onto one row (see
    # UserProfile's module docstring): contact_source always applies since
    # full_name/email are always present; address_source/links_source are
    # nullable because an empty address/links group isn't a fact yet.
    op.add_column(
        "user_profiles",
        sa.Column(
            "contact_source",
            sa.String(length=16),
            nullable=False,
            comment=_PROVENANCE_COMMENT,
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "address_source",
            sa.String(length=16),
            nullable=True,
            comment=_PROVENANCE_COMMENT,
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "links_source",
            sa.String(length=16),
            nullable=True,
            comment=_PROVENANCE_COMMENT,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "links_source")
    op.drop_column("user_profiles", "address_source")
    op.drop_column("user_profiles", "contact_source")

    for table in (
        "eeo_self_identifications",
        "work_authorizations",
        "skills",
        "education_entries",
        "work_history_entries",
    ):
        op.drop_column(table, "source")
