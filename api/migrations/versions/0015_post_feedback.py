"""Add user_feedback column to roundtable_posts.

Revision ID: 0015_post_feedback
Revises: 0014_commons_channels
Create Date: 2026-05-24

Roundtable v2 P2: per-post thumbs up/down. Values: NULL (no
feedback), 'up', 'down'. Feeds into append_session_memory so agents
learn which contributions the user found helpful.
"""

from alembic import op


revision = "0015_post_feedback"
down_revision = "0014_commons_channels"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        try:
            op.execute("ALTER TABLE roundtable_posts ADD COLUMN user_feedback TEXT")
        except Exception:
            pass  # Column already exists (idempotent)


def downgrade() -> None:
    pass  # SQLite cannot drop columns
