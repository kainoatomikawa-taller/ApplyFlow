"""add standard application fields (contact address, links, work
authorization, EEO self-ID)

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors `_SENSITIVE_COMMENT` in src/infrastructure/persistence/models.py —
# these columns hold the same category of data `WorkAuthorization`/
# `EeoSelfIdentification` flag `SENSITIVE = True` in the domain layer.
_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."


def upgrade() -> None:
    # Contact info: postal address, added directly to user_profiles (not
    # sensitive-flagged).
    op.add_column("user_profiles", sa.Column("street_address", sa.String(length=255)))
    op.add_column("user_profiles", sa.Column("city", sa.String(length=255)))
    op.add_column("user_profiles", sa.Column("state_or_region", sa.String(length=255)))
    op.add_column("user_profiles", sa.Column("postal_code", sa.String(length=32)))
    op.add_column("user_profiles", sa.Column("country", sa.String(length=255)))

    # Links: portfolio/LinkedIn/GitHub (not sensitive-flagged).
    op.add_column("user_profiles", sa.Column("portfolio_url", sa.String(length=2048)))
    op.add_column("user_profiles", sa.Column("linkedin_url", sa.String(length=2048)))
    op.add_column("user_profiles", sa.Column("github_url", sa.String(length=2048)))

    # Work authorization / citizenship — sensitive, isolated in its own
    # one-to-one table so Epic 07 can encrypt/restrict it independently of
    # the general profile row.
    op.create_table(
        "work_authorizations",
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, comment=_SENSITIVE_COMMENT
        ),
        sa.Column(
            "citizenship_country",
            sa.String(length=255),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column(
            "visa_type",
            sa.String(length=64),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column(
            "requires_sponsorship",
            sa.Boolean(),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column("details", sa.Text(), nullable=True, comment=_SENSITIVE_COMMENT),
    )

    # EEO self-identification — sensitive, optional, isolated the same way.
    # No default is set on any column: a NULL means "not provided", never
    # an assumed answer.
    op.create_table(
        "eeo_self_identifications",
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "gender_identity",
            sa.String(length=32),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column(
            "race_ethnicity",
            sa.String(length=64),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column(
            "veteran_status",
            sa.String(length=32),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
        sa.Column(
            "disability_status",
            sa.String(length=32),
            nullable=True,
            comment=_SENSITIVE_COMMENT,
        ),
    )


def downgrade() -> None:
    op.drop_table("eeo_self_identifications")
    op.drop_table("work_authorizations")

    op.drop_column("user_profiles", "github_url")
    op.drop_column("user_profiles", "linkedin_url")
    op.drop_column("user_profiles", "portfolio_url")

    op.drop_column("user_profiles", "country")
    op.drop_column("user_profiles", "postal_code")
    op.drop_column("user_profiles", "state_or_region")
    op.drop_column("user_profiles", "city")
    op.drop_column("user_profiles", "street_address")
