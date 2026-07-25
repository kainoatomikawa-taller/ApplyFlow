"""create application_reviews table

The filled application a candidate reviews before sending it, and the record of
them sending it. See `ApplicationReviewModel` for the column-level contract —
notably the partial unique index that allows one review *in progress* per
candidate and posting, and the two sensitive columns.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."


def upgrade() -> None:
    op.create_table(
        "application_reviews",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "job_posting_id",
            sa.String(length=64),
            # CASCADE, like portal_handoffs: a review is the working surface for
            # an application in flight, not the archived record of what was sent
            # (that is application_documents, which uses RESTRICT).
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column(
            "ats_provider",
            sa.String(length=32),
            nullable=False,
            comment=(
                "Which supported ATS platform the form was read as: greenhouse "
                "| lever | ashby. See src/domain/value_objects/ats_provider.py."
            ),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment=(
                "Review lifecycle: in_review | submitted_by_user. Only a "
                "candidate's own action reaches the second. See "
                "src/domain/value_objects/review_status.py."
            ),
        ),
        sa.Column(
            "answers",
            sa.JSON(),
            nullable=False,
            comment=(
                "SENSITIVE: the answers on a real application, plus their "
                "provenance and the candidate's decisions. See "
                "src/domain/value_objects/reviewed_answer.py."
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "screenshot_captured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "submission_note",
            sa.Text(),
            nullable=False,
            server_default="",
            comment=_SENSITIVE_COMMENT,
        ),
    )
    # One review IN PROGRESS per candidate and posting. Submitted rows are
    # exempt: applying to the same posting twice is two real events, and each
    # keeps the answers that were actually sent.
    op.create_index(
        "uq_application_reviews_open_per_job",
        "application_reviews",
        ["user_id", "job_posting_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_review'"),
    )
    op.create_index(
        "ix_application_reviews_job_posting_id",
        "application_reviews",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_application_reviews_user_id_created_at",
        "application_reviews",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_reviews_user_id_created_at",
        table_name="application_reviews",
    )
    op.drop_index(
        "ix_application_reviews_job_posting_id", table_name="application_reviews"
    )
    op.drop_index(
        "uq_application_reviews_open_per_job", table_name="application_reviews"
    )
    op.drop_table("application_reviews")
