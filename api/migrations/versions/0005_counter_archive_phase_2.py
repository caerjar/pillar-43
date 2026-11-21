"""counter-archive phase 2: ca_ghosts, ca_figures, ca_gaps tables

Revision ID: 0005_counter_archive_phase_2
Revises: 0004_hot_query_indexes
Create Date: 2026-04-28

Adds the three SQLite tables that back Phase 2 of the Counter-Archive
Engine: Ghost Layer (Pass 6) and Corpus Gap (Pass 7).

  ca_ghosts   — per-paragraph erasure markers from AI-assisted Pass 6
                (unnamed_actor, broken_reference, temporal_gap,
                passive_construction, redacted, form_silence,
                deferred_presence). evidence_register is the verbatim
                quote — never paraphrased; that invariant is enforced
                by review, not by the schema.
  ca_figures  — corpus-level clusters of recurring unnamed actors.
                name_proxy is "the visitor" or "she," NEVER a guessed
                real name. Validated at the route layer.
  ca_gaps     — pure-DB structural absences from Pass 7 (temporal
                sparse periods, isolated threads, broken wikilinks,
                entity_without_thread, corpus_shadow).

See COUNTER_ARCHIVE_PHASE_2_PLAN.md for the full schema rationale and
the v2 prompt that drives Pass 6.

Idempotent. Safe to run on a fresh DB or one that already has the
baseline tables.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0005_counter_archive_phase_2"
down_revision: Union[str, None] = "0004_hot_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection

    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS ca_figures (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          name_proxy      TEXT    NOT NULL,
          fragment_count  INTEGER NOT NULL DEFAULT 0,
          first_seen_at   REAL    NOT NULL,
          last_seen_at    REAL    NOT NULL,
          dossier_path    TEXT,
          computed_at     REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ca_ghosts (
          id                INTEGER PRIMARY KEY AUTOINCREMENT,
          source_path       TEXT    NOT NULL,
          source_line       INTEGER NOT NULL,
          paragraph_hash    TEXT    NOT NULL,
          erasure_type      TEXT    NOT NULL,
          evidence_register TEXT    NOT NULL,
          inference_grade   TEXT    NOT NULL,
          confidence        REAL    NOT NULL,
          scanned_at        REAL    NOT NULL,
          figure_id         INTEGER,
          FOREIGN KEY (figure_id) REFERENCES ca_figures(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ca_ghosts_path
          ON ca_ghosts(source_path);
        CREATE INDEX IF NOT EXISTS idx_ca_ghosts_figure
          ON ca_ghosts(figure_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ca_ghosts_dedup
          ON ca_ghosts(source_path, source_line, paragraph_hash);

        CREATE TABLE IF NOT EXISTS ca_gaps (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          gap_type     TEXT    NOT NULL,
          evidence     TEXT    NOT NULL,
          score        REAL    NOT NULL,
          computed_at  REAL    NOT NULL,
          details_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ca_gaps_type
          ON ca_gaps(gap_type);
        CREATE INDEX IF NOT EXISTS idx_ca_gaps_score
          ON ca_gaps(score DESC);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_ca_gaps_score;
        DROP INDEX IF EXISTS idx_ca_gaps_type;
        DROP TABLE IF EXISTS ca_gaps;
        DROP INDEX IF EXISTS idx_ca_ghosts_dedup;
        DROP INDEX IF EXISTS idx_ca_ghosts_figure;
        DROP INDEX IF EXISTS idx_ca_ghosts_path;
        DROP TABLE IF EXISTS ca_ghosts;
        DROP TABLE IF EXISTS ca_figures;
        """
    )
