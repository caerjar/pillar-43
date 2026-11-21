"""commons_channels.is_ambient — per-channel opt-in for unprompted speech

Revision ID: 0020_commons_ambient
Revises: 0019_commons_topics
Create Date: 2026-08-10

Separate from `is_research` (0019), which governs whether *other instances'
agents* get answered here. This governs whether the agent may treat an
unaddressed human message as meant for it — a different question with a
different blast radius, and one that would be wrong to grant implicitly by
turning on the other.

Two consumers:

  - the `question` addressing signal, which is ambient in substance (the agent
    deciding a question was for it) and so is gated on this rather than
    shipping wherever speak is enabled;
  - the observe-only ambient evaluation, which spends a model call per
    candidate post to decide whether it *would* speak, and must not run
    everywhere by default.

Nullable, NULL reads as off. Same convention as `consent_level` and
`is_research`: no backfill, and an existing channel cannot acquire the
behaviour by being upgraded.

Idempotent. Safe on a fresh DB or one already at 0019.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0020_commons_ambient"
down_revision: Union[str, None] = "0019_commons_topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    cols = {row[1] for row in raw.execute("PRAGMA table_info(commons_channels)")}
    if "is_ambient" not in cols:
        raw.execute("ALTER TABLE commons_channels ADD COLUMN is_ambient INTEGER")


def downgrade() -> None:
    # SQLite before 3.35 cannot DROP COLUMN and a stray nullable flag is
    # harmless. Same choice as 0016 and 0019.
    pass
