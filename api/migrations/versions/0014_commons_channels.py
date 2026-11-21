"""commons_channels table + roundtable_sessions.commons_channel_id

Revision ID: 0014_commons_channels
Revises: 0013_file_connections_dismissed
Create Date: 2026-05-18

Sprint A Day 1. Schema for Commons (v0.3.2).

Schema decisions:

  - id is TEXT (UUID). Same forward-compat reasoning as
    roundtable_sessions (0011): channels exist on multiple instances
    after Sprint B's federation work, need cross-vault unique IDs.

  - slug TEXT UNIQUE. Human-readable; also used to derive
    generated/commons/<slug>/ paths so it must be filesystem-safe. Slug
    validation enforced at the service layer (services/commons/manifest.py
    on write).

  - mattermost_url + mattermost_channel_id are TEXT. The Mattermost
    server URL and channel ID together uniquely address a remote channel.
    We allow multiple Commons against the same MM server (UNIQUE only on
    slug, not on the URL+channel_id pair) so two local instances on the
    same MM can join the same room with different local slugs.

  - polling_interval_sec INTEGER default 30. Per PRD §212 each channel
    can override the default. 30s is the v1 default; webhooks deferred
    to v2 (PRD §275).

  - enabled INTEGER. SQLite has no real BOOL; 0/1 with default 1. A
    disabled channel keeps its row + posts.md but the polling job
    skips it.

  - last_polled_at REAL nullable. Wall-clock epoch seconds. Polling
    uses this to compute "fetch posts since" on each tick.

  - roundtable_sessions.commons_channel_id is a nullable TEXT column.
    NOT a hard FK — same rationale as roundtable_posts.agent_name
    (0011 comment): TEXT IDs accommodate cross-vault references and a
    deleted channel's prior sessions stay readable. Backward-compatible:
    pre-Commons sessions have NULL and behave exactly as before.

Idempotent. Safe on a fresh DB or one already at 0013.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0014_commons_channels"
down_revision: Union[str, None] = "0013_file_connections_dismissed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS commons_channels (
          id                    TEXT    PRIMARY KEY,
          slug                  TEXT    NOT NULL UNIQUE,
          mattermost_url        TEXT    NOT NULL,
          mattermost_channel_id TEXT    NOT NULL,
          polling_interval_sec  INTEGER NOT NULL DEFAULT 30,
          enabled               INTEGER NOT NULL DEFAULT 1,
          last_polled_at        REAL,
          created_at            REAL    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_commons_channels_enabled
          ON commons_channels(enabled) WHERE enabled = 1;
        """
    )

    # ALTER TABLE ADD COLUMN — SQLite supports this only for non-NOT-NULL
    # columns without an inline default. Guard with a column-existence check
    # so the migration is idempotent on partial re-runs.
    cur = raw.execute("PRAGMA table_info(roundtable_sessions)")
    cols = {row[1] for row in cur.fetchall()}
    if "commons_channel_id" not in cols:
        raw.execute(
            "ALTER TABLE roundtable_sessions ADD COLUMN commons_channel_id TEXT"
        )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    # SQLite < 3.35 can't DROP COLUMN; we leave the column in place on
    # downgrade. The data dropping below is destructive enough already.
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_commons_channels_enabled;
        DROP TABLE IF EXISTS commons_channels;
        """
    )
