"""commons_holds (outbound approval queue) + consent columns on commons_channels

Revision ID: 0016_commons_consent
Revises: 0015_post_feedback
Create Date: 2026-07-02

Outbound consent loop (PRD §378-417). Before an agent's post leaves for a
Commons, the filter + a per-channel consent level decide whether it
publishes now or waits in the approval queue.

Schema decisions:

  - commons_holds is a DB table, NOT a posts.md block: a hold has MUTABLE
    status (pending → approved/rejected/published), and posts.md is
    append-only (the maintainer notes). id is TEXT (UUID), same cross-vault
    forward-compat reasoning as the other commons IDs.

  - reason distinguishes WHY a post was queued: 'filter_hold' (the filter
    flagged it — held even under trust_all) vs 'consent' (the channel's
    consent level requires review). A 'filter_hold' approval is a
    force-publish.

  - consent_level / trust_n are nullable on commons_channels: NULL means "use
    the global default" (config.effective_commons_consent_default / _trust_n).
    auto_publish_count is the monotonic counter for trust_after_n, bumped ONLY
    on a "trust this kind" approval; single-writer via channel_store.

Idempotent. Safe on a fresh DB or one already at 0015.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0016_commons_consent"
down_revision: Union[str, None] = "0015_post_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS commons_holds (
          id             TEXT    PRIMARY KEY,
          channel_slug   TEXT    NOT NULL,
          post_body      TEXT    NOT NULL,
          agent_slug     TEXT,
          peer           TEXT,
          rationale      TEXT    NOT NULL DEFAULT '',
          confidence     REAL    NOT NULL DEFAULT 0.0,
          reason         TEXT    NOT NULL DEFAULT 'consent',
          status         TEXT    NOT NULL DEFAULT 'pending',
          created_at     REAL    NOT NULL,
          resolved_at    REAL,
          mattermost_id  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_commons_holds_channel_status
          ON commons_holds(channel_slug, status);
        """
    )

    # ALTER TABLE ADD COLUMN — guard each with a column-existence check so the
    # migration is idempotent on partial re-runs.
    cur = raw.execute("PRAGMA table_info(commons_channels)")
    cols = {row[1] for row in cur.fetchall()}
    if "consent_level" not in cols:
        raw.execute("ALTER TABLE commons_channels ADD COLUMN consent_level TEXT")
    if "trust_n" not in cols:
        raw.execute("ALTER TABLE commons_channels ADD COLUMN trust_n INTEGER")
    if "auto_publish_count" not in cols:
        raw.execute(
            "ALTER TABLE commons_channels "
            "ADD COLUMN auto_publish_count INTEGER NOT NULL DEFAULT 0"
        )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    # SQLite < 3.35 can't DROP COLUMN; leave the added columns in place.
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_commons_holds_channel_status;
        DROP TABLE IF EXISTS commons_holds;
        """
    )
