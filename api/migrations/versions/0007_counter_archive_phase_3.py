"""counter-archive phase 3: ca_detritus, ca_sessions, ca_interactions

Revision ID: 0007_counter_archive_phase_3
Revises: 0006_ghost_dedup_per_type
Create Date: 2026-04-29

Adds the three SQLite tables that back Phase 3 of the Counter-Archive
Engine: Detritus (noise as testimony) and Archive Reads You Back
(session logging + end-of-session fabulation).

  ca_detritus     — per-fragment OCR / hyphenation / Unicode artifacts
                    from `services/catalog/detritus.py`. The `fragment`
                    field is the verbatim slice — never normalized.
                    `interpretation` is NULL until a Day 2 interpret
                    call fills it via a hosted model (Hartman-grounded prompt).
  ca_sessions     — counter-archive-mode session boundaries. One row
                    per mode-on event. `ended_at` is NULL while open;
                    set on idle-30min or mode-off. Open-session lookup
                    uses the partial index.
  ca_interactions — append-only event log within a session. Five
                    event_type enum values: ghost_viewed,
                    opacity_overridden, gap_examined, file_skipped,
                    file_dwelled. Privacy invariant: paths logged,
                    file content NEVER logged.

The Apparatus engine (also Phase 3) does NOT need a table — its schema-
critique cache lives at generated/_apparatus_schema_critique.txt keyed
by sha256(schema_dump).

See COUNTER_ARCHIVE_PHASE_3_PLAN.md for the full schema rationale and
the Hartman-grounded prompts that drive interpretation + fabulation.

Idempotent. Safe to run on a fresh DB or one that already has 0006.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0007_counter_archive_phase_3"
down_revision: Union[str, None] = "0006_ghost_dedup_per_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection

    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS ca_detritus (
          id                INTEGER PRIMARY KEY AUTOINCREMENT,
          source_path       TEXT    NOT NULL,
          source_line       INTEGER NOT NULL,
          fragment          TEXT    NOT NULL,
          detritus_type     TEXT    NOT NULL,
          context_before    TEXT,
          context_after     TEXT,
          scanned_at        REAL    NOT NULL,
          interpretation    TEXT,
          interpretation_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_ca_detritus_path
          ON ca_detritus(source_path);
        CREATE INDEX IF NOT EXISTS idx_ca_detritus_type
          ON ca_detritus(detritus_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ca_detritus_dedup
          ON ca_detritus(source_path, source_line, fragment);

        CREATE TABLE IF NOT EXISTS ca_sessions (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at      REAL    NOT NULL,
          ended_at        REAL,
          event_count     INTEGER NOT NULL DEFAULT 0,
          fabulation_path TEXT,
          fabulation_at   REAL
        );

        -- Partial index: open sessions are the hot query
        CREATE INDEX IF NOT EXISTS idx_ca_sessions_open
          ON ca_sessions(started_at) WHERE ended_at IS NULL;

        CREATE TABLE IF NOT EXISTS ca_interactions (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id   INTEGER NOT NULL,
          occurred_at  REAL    NOT NULL,
          event_type   TEXT    NOT NULL,
          target_path  TEXT,
          target_id    INTEGER,
          details_json TEXT,
          FOREIGN KEY (session_id) REFERENCES ca_sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ca_interactions_session
          ON ca_interactions(session_id);
        CREATE INDEX IF NOT EXISTS idx_ca_interactions_type
          ON ca_interactions(event_type);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_ca_interactions_type;
        DROP INDEX IF EXISTS idx_ca_interactions_session;
        DROP TABLE IF EXISTS ca_interactions;
        DROP INDEX IF EXISTS idx_ca_sessions_open;
        DROP TABLE IF EXISTS ca_sessions;
        DROP INDEX IF EXISTS idx_ca_detritus_dedup;
        DROP INDEX IF EXISTS idx_ca_detritus_type;
        DROP INDEX IF EXISTS idx_ca_detritus_path;
        DROP TABLE IF EXISTS ca_detritus;
        """
    )
