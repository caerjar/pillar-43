"""baseline: full catalog schema as of sprint 12

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-27

This migration produces the EXACT schema state that init_schema() used to
build via `_SCHEMA + _migrate_*` functions. Live databases that already
have this schema get stamped at this revision (no DDL runs).

The schema SQL itself lives in `services/_schema_baseline.py` so the
in-memory test fallback can apply the same statements without going through
Alembic. After this baseline, every schema change is a new migration file.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from services._schema_baseline import BASELINE_SQL


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the frozen baseline schema."""
    bind = op.get_bind()
    # SQLAlchemy → DBAPI sqlite3.Connection. Use executescript() because the
    # schema includes CREATE TRIGGER statements with semicolons in their bodies.
    raw = bind.connection.driver_connection
    raw.executescript(BASELINE_SQL)


def downgrade() -> None:
    """Drop everything created by upgrade.

    Useful for tests; not safe against a DB with data unless you really want
    to start over. Order: triggers → tables, with FK dependencies reversed.
    """
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript("""
        DROP TRIGGER IF EXISTS files_fts_delete;
        DROP TRIGGER IF EXISTS files_fts_update;
        DROP TRIGGER IF EXISTS files_fts_insert;
        DROP TABLE IF EXISTS ca_opacity;
        DROP TABLE IF EXISTS file_checkpoints;
        DROP TABLE IF EXISTS tasks;
        DROP TABLE IF EXISTS topic_aliases;
        DROP TABLE IF EXISTS threads;
        DROP TABLE IF EXISTS file_connections;
        DROP TABLE IF EXISTS files_fts;
        DROP TABLE IF EXISTS files;
    """)
