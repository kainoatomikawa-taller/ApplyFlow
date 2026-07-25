"""create application_documents table

Immutable snapshots of the exact resume/cover letter produced for a job
posting. See `ApplicationDocumentModel` for the column-level contract
(write-once, digest-verified, sensitive content, RESTRICT on the posting FK).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."
_PROVENANCE_COMMENT = (
    "Fact provenance: parsed_resume | user_entered | answer. "
    "Required — see src/domain/value_objects/provenance_source.py."
)


def upgrade() -> None:
    op.create_table(
        "application_documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "job_posting_id",
            sa.String(length=64),
            # RESTRICT, not CASCADE: a record of what was actually sent to an
            # employer must not vanish when a job posting is pruned.
            sa.ForeignKey("job_postings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_kind",
            sa.String(length=32),
            nullable=False,
            comment=(
                "Generated document kind: tailored_resume | cover_letter. "
                "See src/domain/value_objects/generated_document_kind.py."
            ),
        ),
        sa.Column("content", sa.Text(), nullable=False, comment=_SENSITIVE_COMMENT),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "backing_sources", sa.JSON(), nullable=False, comment=_PROVENANCE_COMMENT
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Two rows claiming the same version of the same document for the same
        # job is an ambiguity the tracker would have to guess about, so it is a
        # database error instead.
        sa.UniqueConstraint(
            "user_id",
            "job_posting_id",
            "document_kind",
            "version",
            name="uq_application_documents_version",
        ),
    )
    op.create_index(
        "ix_application_documents_job_posting_id",
        "application_documents",
        ["job_posting_id"],
    )
    op.create_index(
        "ix_application_documents_user_id_created_at",
        "application_documents",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_documents_user_id_created_at",
        table_name="application_documents",
    )
    op.drop_index(
        "ix_application_documents_job_posting_id",
        table_name="application_documents",
    )
    op.drop_table("application_documents")
