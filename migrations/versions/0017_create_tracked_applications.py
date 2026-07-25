"""create tracked_applications table

The tracker's spine (Epic 06): one row per application the candidate actually
sent — role, company, date applied, status, the job posting it came from, and
references to the exact resume and cover letter snapshots that went with it.

See `TrackedApplicationModel` for the column-level contract. The two decisions
worth reading there before changing anything here: every foreign key is
RESTRICT (this is the archived record of a sent application, so it must outlive
its posting being pruned), and there is deliberately no unique constraint on
(user_id, job_posting_id) because applying to the same posting twice is two
real events.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tracked_applications",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "job_posting_id",
            sa.String(length=64),
            # RESTRICT, like application_documents: this row records an
            # application that was actually sent, so it must not disappear as a
            # side effect of pruning postings. (application_reviews and
            # portal_handoffs use CASCADE — they are in-flight state.)
            sa.ForeignKey("job_postings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Copied from the posting at record time, so a posting later retitled
        # or re-normalized cannot rewrite what this application was for.
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("role_title", sa.String(length=255), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment=(
                "Application lifecycle: applied | interviewing | offer | "
                "rejected | withdrawn. Never 'draft' — an application still "
                "being prepared is an application_reviews row. See "
                "src/domain/value_objects/application_status.py."
            ),
        ),
        # The exact snapshots the employer received (Epic 04), referenced
        # rather than copied. Note what the FK cannot enforce: that the target
        # is the right *kind* of document and belongs to this candidate and
        # posting — that check is in TrackedApplication.record_sent.
        sa.Column(
            "resume_document_id",
            sa.String(length=64),
            sa.ForeignKey("application_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cover_letter_document_id",
            sa.String(length=64),
            sa.ForeignKey("application_documents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_tracked_applications_job_posting_id",
        "tracked_applications",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_tracked_applications_resume_document_id",
        "tracked_applications",
        ["resume_document_id"],
    )
    op.create_index(
        "ix_tracked_applications_cover_letter_document_id",
        "tracked_applications",
        ["cover_letter_document_id"],
    )
    # The tracker's feed: a candidate's applications, most recent first.
    op.create_index(
        "ix_tracked_applications_user_id_applied_at",
        "tracked_applications",
        ["user_id", "applied_at"],
    )
    # "What is still live?" — filters on status before ordering.
    op.create_index(
        "ix_tracked_applications_user_id_status",
        "tracked_applications",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tracked_applications_user_id_status", table_name="tracked_applications"
    )
    op.drop_index(
        "ix_tracked_applications_user_id_applied_at", table_name="tracked_applications"
    )
    op.drop_index(
        "ix_tracked_applications_cover_letter_document_id",
        table_name="tracked_applications",
    )
    op.drop_index(
        "ix_tracked_applications_resume_document_id",
        table_name="tracked_applications",
    )
    op.drop_index(
        "ix_tracked_applications_job_posting_id", table_name="tracked_applications"
    )
    op.drop_table("tracked_applications")
