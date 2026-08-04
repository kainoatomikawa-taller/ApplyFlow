"""add user_profiles.middle_name and preferred_name

The last two identity fields an ATS application form asks for. The label
recognizer has always mapped them (`MIDDLE_NAME`, `PREFERRED_NAME` in
`ApplicationFieldSlot`) so the generic name rules could not claim them, but no
profile field answered either — so both questions went to the candidate on every
application. These columns are what let the profile answer them.

Both are encrypted, for the same reason `full_name` is: a middle name and the
name someone goes by are as identifying as the legal one, and a database holding
all three is not improved by protecting only the first. See
`UserProfileModel` for the column-level contract.

Nullable, with no backfill and no default — and the absence carries meaning
rather than being missing data:

- `middle_name` NULL means "no middle name". A form asking for one gets nothing
  written into it rather than being handed back to the candidate.
- `preferred_name` NULL means "the same name I go by legally", so the slot falls
  back to the first name derived from `full_name`.

Both readings are applied in `src/domain/services/profile_field_values.py`; this
migration only makes the storage exist. Existing profiles therefore start as
"no middle name, no distinct preferred name", which is the correct reading of a
profile written before the fields existed — the candidate was never asked.

No `server_default`. A server-side default on an encrypted column inserts
plaintext that nothing can decrypt; migrations 0021 and 0023 both had to drop
one, and this migration avoids adding a third.

Nothing to encrypt on the way up, since both columns start empty — which makes
this the one encrypted-column migration in this schema that needs no data pass
and no keyring. `downgrade()` drops both columns, discarding whatever was
entered; that is a real data loss and is why it is stated rather than implied.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Matches `_SENSITIVE_COMMENT` in models.py — what someone reading `\d` sees.
_SENSITIVE_COMMENT = (
    "SENSITIVE: AES-256-GCM encrypted at rest (Epic 07). Not queryable by "
    "value; decrypts only inside a declared access scope. Never log."
)


def upgrade() -> None:
    # `Text`, like every other encrypted column: ciphertext has no length and
    # no useful type, so the Python-side `str` is enforced by the column type
    # rather than by the database.
    for column in ("middle_name", "preferred_name"):
        op.add_column(
            "user_profiles",
            sa.Column(
                column,
                sa.Text(),
                nullable=True,
                comment=_SENSITIVE_COMMENT,
            ),
        )


def downgrade() -> None:
    for column in ("preferred_name", "middle_name"):
        op.drop_column("user_profiles", column)
