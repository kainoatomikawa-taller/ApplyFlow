"""add job_location to tracked_applications

What it is for: feeding the tracker back into matching, so a candidate is not
nudged to apply again to a role they have already applied to. The match is on
the job's canonical identity — company + title + location — and the first two
were already snapshotted on this table (see 0017). This adds the third.

Location has to be stored here rather than read through `job_posting_id`, for
the same reason company and title already are, plus one specific to this
feature: suppression must keep working after the posting the application went
through is pruned, relisted under a new id, or re-ingested from another
aggregator. Those are precisely the cases where a join gives no answer and the
candidate would be nudged to re-apply.

Nullable, with no backfill. A pre-existing row genuinely does not know the
posting's location as of send time, and the honest value is NULL — the domain
treats "no location" as its own identity component, so such a row matches only
postings that also name no location. That under-suppresses (the candidate may
see one already-applied job again) rather than over-suppresses (hiding a job
they never applied to), which is the right way for this to fail. Backfilling
from `job_postings` would look tidier and would assert, for every old row, that
today's posting location was the one at send time.

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
    op.add_column(
        "tracked_applications",
        sa.Column(
            "job_location",
            sa.String(length=255),
            nullable=True,
            comment=(
                "The posting's location as of send time. With company_name "
                "and role_title this forms the canonical role identity that "
                "keeps already-applied jobs out of the candidate's matches — "
                "see src/domain/value_objects/canonical_job_identity.py."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("tracked_applications", "job_location")
