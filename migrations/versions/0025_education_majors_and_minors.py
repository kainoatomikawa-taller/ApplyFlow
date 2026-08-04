"""Replace education_entries.field_of_study with majors and minors arrays.

A double major is two facts, and one `field_of_study` string could only hold it
by joining the two and losing which was which. Minors are added as a separate
column rather than folded in, because "minor in Economics" is a weaker claim than
"major in Economics" and a tailored résumé must not be able to promote one to the
other.

`field_of_study` survives as a derived property on the entity (the majors joined)
for the single form box an application normally offers, so nothing downstream
needed a new concept — only this column had to go, to keep one source of truth.

Data: every existing `field_of_study` becomes the entry's single major. The
downgrade reverses it by taking the first major, which is lossy for anyone who
recorded two — unavoidable in the narrower shape, and called out here rather than
discovered later.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no server default: NULL and [] both read as "none stated",
    # so there is nothing for a default to usefully say, and backfilling every
    # row to '[]' would rewrite rows this change does not otherwise touch.
    op.add_column("education_entries", sa.Column("majors", sa.JSON(), nullable=True))
    op.add_column("education_entries", sa.Column("minors", sa.JSON(), nullable=True))

    # json_build_array (not to_jsonb) so the result is a JSON *array* of one
    # string, matching what the ORM writes. Rows with a NULL or blank
    # field_of_study are left NULL rather than becoming [""], which the entity
    # would strip anyway.
    op.execute(
        """
        UPDATE education_entries
           SET majors = json_build_array(field_of_study)
         WHERE field_of_study IS NOT NULL
           AND btrim(field_of_study) <> ''
        """
    )

    op.drop_column("education_entries", "field_of_study")


def downgrade() -> None:
    op.add_column(
        "education_entries",
        sa.Column("field_of_study", sa.String(length=255), nullable=True),
    )
    # ->> 0 extracts the first element as text. Truncated to 255 to fit the
    # restored column; a second or third major is dropped, as the docstring says.
    op.execute(
        """
        UPDATE education_entries
           SET field_of_study = left(majors::jsonb ->> 0, 255)
         WHERE majors IS NOT NULL
           AND json_array_length(majors) > 0
        """
    )
    op.drop_column("education_entries", "minors")
    op.drop_column("education_entries", "majors")
