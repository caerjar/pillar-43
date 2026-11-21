"""agent harness: roundtable_sessions + roundtable_posts (UUID-keyed)

Revision ID: 0011_agent_harness
Revises: 0010_counterfactuals
Create Date: 2026-04-30

Sprint 94. The Agent Harness convenes named agents (Fabulator, Grain
Reader, Opacity Keeper, Angel, Mourner, Unlearner, Ritualist,
Archaeologist, Futurist, Substrate) in a forum-style roundtable.
Each session produces a vault artifact at notes/roundtables/<slug>.md.

Schema decisions worth flagging:

  - id is TEXT (UUID), not INTEGER autoincrement. Forward-compat hook
    for Commons shared-room replication where
    sessions exist on multiple instances simultaneously and need
    cross-vault unique identifiers. UUIDs cost nothing today; integer
    IDs would require a painful migration later. Existing tables
    (ca_*, files, threads, etc.) stay autoincrement — only the
    roundtable surface needs cross-vault uniqueness.

  - agent_name is TEXT, not FK to agent identity files. Agents live
    as markdown files (notes/settings/agents/<slug>.md), not DB rows.
    The TEXT column accommodates federation: Sprint 96 stores
    "peer:slug"; Commons stores "commons:peer:slug".
    A retired or deleted agent's prior posts stay readable.

  - reply_to_post_id ON DELETE SET NULL. If a post is admin-deleted
    (future feature), its replies become orphaned but stay in the
    artifact. Same pattern as ca_potentials.source_gap_id.

  - sessions are rootless — no required parent container. Sprint 95
    adds a `channels` table with `sessions.channel_id` (nullable) for
    backward compat. Sprint 97 may add a `spaces` / `collections`
    layer above channels. Keeping sessions rootless means any of
    those drop in without a session-table migration.

Idempotent. Safe to run on a fresh DB or one that already has 0010.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0011_agent_harness"
down_revision: Union[str, None] = "0010_counterfactuals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS roundtable_sessions (
          id           TEXT    PRIMARY KEY,
          slug         TEXT    NOT NULL UNIQUE,
          topic        TEXT    NOT NULL,
          agents_json  TEXT    NOT NULL,
          rounds       INTEGER NOT NULL,
          output_path  TEXT    NOT NULL UNIQUE,
          status       TEXT    NOT NULL DEFAULT 'running',
          started_at   REAL    NOT NULL,
          ended_at     REAL,
          error        TEXT,
          source_file  TEXT
        );

        CREATE TABLE IF NOT EXISTS roundtable_posts (
          id                TEXT    PRIMARY KEY,
          session_id        TEXT    NOT NULL REFERENCES roundtable_sessions(id) ON DELETE CASCADE,
          agent_name        TEXT    NOT NULL,
          round_num         INTEGER NOT NULL,
          reply_to_post_id  TEXT    REFERENCES roundtable_posts(id) ON DELETE SET NULL,
          text              TEXT    NOT NULL,
          created_at        REAL    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rt_posts_session
          ON roundtable_posts(session_id);
        CREATE INDEX IF NOT EXISTS idx_rt_posts_round
          ON roundtable_posts(session_id, round_num);
        CREATE INDEX IF NOT EXISTS idx_rt_sessions_open
          ON roundtable_sessions(started_at) WHERE ended_at IS NULL;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_rt_sessions_open;
        DROP INDEX IF EXISTS idx_rt_posts_round;
        DROP INDEX IF EXISTS idx_rt_posts_session;
        DROP TABLE IF EXISTS roundtable_posts;
        DROP TABLE IF EXISTS roundtable_sessions;
        """
    )
