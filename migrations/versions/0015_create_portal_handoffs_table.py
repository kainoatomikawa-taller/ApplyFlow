"""create portal_handoffs table

Application portals where automation stopped at a hard boundary (a CAPTCHA, an
e-signature, a sign-in wall) and handed control to the candidate. See
`PortalHandoffModel` for the column-level contract — notably the partial
unique index that allows at most one *open* hand-off per candidate and
posting, and the sensitive resolution note.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."


def upgrade() -> None:
    op.create_table(
        "portal_handoffs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "job_posting_id",
            sa.String(length=64),
            # CASCADE, unlike application_documents' RESTRICT: a hand-off is
            # an in-flight interaction with a portal, not a record of what was
            # sent to an employer. With the posting gone there is no
            # application left to resume.
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column(
            "paused_url",
            sa.Text(),
            nullable=False,
            comment=(
                "Where automation stopped — often a redirect target, and the "
                "URL the candidate is pointed at to finish the step."
            ),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment=(
                "Hand-off lifecycle: awaiting_user | resumed | abandoned. "
                "See src/domain/value_objects/handoff_status.py."
            ),
        ),
        sa.Column(
            "hard_stops",
            sa.JSON(),
            nullable=False,
            comment=(
                "Detected hard boundaries: kind + evidence lines about the "
                "portal's page. See src/domain/value_objects/hard_stop.py."
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution_note",
            sa.Text(),
            nullable=False,
            server_default="",
            comment=_SENSITIVE_COMMENT,
        ),
    )
    # At most one OPEN hand-off per candidate and posting. Two concurrent
    # inspections would otherwise each raise one, and the candidate would be
    # asked to do the same thing twice. Resolved rows are exempt on purpose: a
    # portal that walls, gets resolved, and walls again is a sequence of real
    # events, and each keeps its own evidence.
    op.create_index(
        "uq_portal_handoffs_open_per_job",
        "portal_handoffs",
        ["user_id", "job_posting_id"],
        unique=True,
        postgresql_where=sa.text("status = 'awaiting_user'"),
    )
    op.create_index(
        "ix_portal_handoffs_job_posting_id", "portal_handoffs", ["job_posting_id"]
    )
    op.create_index(
        "ix_portal_handoffs_user_id_created_at",
        "portal_handoffs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portal_handoffs_user_id_created_at", table_name="portal_handoffs"
    )
    op.drop_index("ix_portal_handoffs_job_posting_id", table_name="portal_handoffs")
    op.drop_index("uq_portal_handoffs_open_per_job", table_name="portal_handoffs")
    op.drop_table("portal_handoffs")
