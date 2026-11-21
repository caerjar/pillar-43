"""commons_topics + commons_channels.is_research — bounded agent-to-agent research

Revision ID: 0019_commons_topics
Revises: 0018_drop_removed_feature_tables
Create Date: 2026-08-09

Until now two instances could not converse at all: `polling.tick` replies only
to posts authored `mattermost:` (humans), so a peer's post arrived under
`commons:<peer>`, was archived, and was never answered. That check is
also what stops the bot answering itself, so it cannot simply be removed — it
has to be replaced with something bounded. A *topic* is that bound.

Schema decisions:

  - **A DB table, not a posts.md block.** Same reasoning as `commons_holds`
    (0016): a topic's turn count is MUTABLE and posts.md is append-only. `id`
    is TEXT (UUID) to match the other commons IDs.

  - **`turns_today` + `turns_day` rather than a timestamp scan.** The budget is
    a daily rate limit, and storing the date the counter belongs to makes the
    reset a string comparison at read time — no scheduler, no cron, no clock
    to inject in tests. Pass a date in and the arithmetic is deterministic.

  - **`opened_by` distinguishes `keeper` from `agent`.** Agents may open topics
    themselves, so the per-day cap on topic CREATION applies only to
    agent-opened ones; a keeper asking a question should never be rate-limited
    by what the agent did earlier. Without the column that distinction cannot
    be made after the fact.

  - **`is_research` is nullable on commons_channels**, NULL meaning off. Same
    convention as `consent_level` — a nullable column reads as "not
    configured" rather than requiring a backfill, and an existing channel must
    not silently become an agent-to-agent channel on upgrade.

Deliberately NOT here: a lifetime turn cap. The budget is a daily rate limit
by explicit choice, which bounds the rate but not the total — a forgotten
topic can keep spending a little each day. `turns_total` would be one more
column and one comparison if that ever bites; the row is already the right
place to hang it.

Idempotent. Safe on a fresh DB or one already at 0018.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0019_commons_topics"
down_revision: Union[str, None] = "0018_drop_removed_feature_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS commons_topics (
          id            TEXT    PRIMARY KEY,
          channel_slug  TEXT    NOT NULL,
          question      TEXT    NOT NULL,
          opened_by     TEXT    NOT NULL DEFAULT 'keeper',
          state         TEXT    NOT NULL DEFAULT 'open',
          turns_today   INTEGER NOT NULL DEFAULT 0,
          turns_day     TEXT    NOT NULL DEFAULT '',
          created_at    REAL    NOT NULL,
          last_turn_at  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_commons_topics_open
          ON commons_topics(channel_slug, state);
        CREATE INDEX IF NOT EXISTS idx_commons_topics_created
          ON commons_topics(opened_by, created_at);
        """
    )

    # SQLite has no ADD COLUMN IF NOT EXISTS; probe first so a re-run is safe.
    cols = {row[1] for row in raw.execute("PRAGMA table_info(commons_channels)")}
    if "is_research" not in cols:
        raw.execute("ALTER TABLE commons_channels ADD COLUMN is_research INTEGER")


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    # The added column is left in place: SQLite before 3.35 cannot DROP COLUMN,
    # and a stray nullable flag is harmless. Same choice as 0016.
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_commons_topics_created;
        DROP INDEX IF EXISTS idx_commons_topics_open;
        DROP TABLE IF EXISTS commons_topics;
        """
    )
