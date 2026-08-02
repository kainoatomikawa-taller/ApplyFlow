"""create application_status_events table

Preserves the status history of every tracked application (Epic 06): one row per
recorded move, so "applied → interviewing → rejected" survives as the sequence
it was rather than collapsing into whatever the status happens to be now. That
history is what follow-ups and interview prep read — "applied three weeks ago,
no reply" and "second round on the 14th" are both questions about *when* an
application changed, and a single status column cannot answer either.

See `ApplicationStatusEventModel` for the column-level contract. The decisions
worth reading there before changing anything here: the primary key is
(tracked_application_id, sequence) with no surrogate id, because a status change
has no identity of its own beyond its position in one application's history; and
this is the one foreign key on the tracker that CASCADEs, because history is
part of its application rather than a reference to it.

Backfill: every existing tracked application gets a sequence-0 row recording the
status it currently holds, dated `applied_at`. That is the truthful reading of a
row written before history was tracked — it holds a status and knows when it was
sent, which is exactly a one-entry history. Without it those applications would
load with an empty history, and the domain would seed the same entry on every
read instead of once, at write time (see `TrackedApplication._validate_history`).

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_status_events",
        sa.Column(
            "tracked_application_id",
            sa.String(length=64),
            # CASCADE, unlike every other FK on the tracker: this is a part-of
            # relationship, and history without its application is unreadable.
            # The application itself is still protected from a posting being
            # pruned by the RESTRICT on tracked_applications.
            sa.ForeignKey("tracked_applications.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        # 0-based and gap-free, so the primary key doubles as the ordering:
        # two changes recorded in the same clock tick still have a definite
        # order, which changed_at alone could not give them.
        sa.Column("sequence", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment=(
                "The status moved to: applied | interviewing | offer | "
                "rejected | withdrawn. Never 'draft'. See "
                "src/domain/value_objects/application_status.py."
            ),
        ),
        sa.Column(
            "previous_status",
            sa.String(length=32),
            nullable=True,
            comment=(
                "The status moved from; NULL only for sequence 0, the entry "
                "recorded when the application was sent."
            ),
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "note",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="The candidate's own note about this change. Do not log.",
        ),
    )
    # The history of one application, in order — the read behind every tracker
    # detail view, and the pair the repository appends against.
    op.create_index(
        "ix_application_status_events_application_sequence",
        "application_status_events",
        ["tracked_application_id", "sequence"],
    )
    # "Which applications ever reached this status, and when?" — the funnel
    # questions scan by status and date rather than by application.
    op.create_index(
        "ix_application_status_events_status_changed_at",
        "application_status_events",
        ["status", "changed_at"],
    )
    # Backfill each existing application's one-entry history. `previous_status`
    # is left NULL and `sequence` 0: nothing preceded the application being
    # sent. Idempotent via NOT EXISTS, so re-running against a partially
    # migrated database cannot produce a duplicate key.
    op.execute(
        """
        INSERT INTO application_status_events (
            tracked_application_id, sequence, status, previous_status,
            changed_at, note
        )
        SELECT ta.id, 0, ta.status, NULL, ta.applied_at, ''
        FROM tracked_applications AS ta
        WHERE NOT EXISTS (
            SELECT 1 FROM application_status_events AS ase
            WHERE ase.tracked_application_id = ta.id
        )
        """
    )


def downgrade() -> None:
    # Dropping the table discards the recorded history. That is the honest
    # consequence of reverting this migration: `tracked_applications.status`
    # still holds where each application stands, which is all the schema
    # before 0019 could represent.
    op.drop_index(
        "ix_application_status_events_status_changed_at",
        table_name="application_status_events",
    )
    op.drop_index(
        "ix_application_status_events_application_sequence",
        table_name="application_status_events",
    )
    op.drop_table("application_status_events")
