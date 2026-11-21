"""drop the Counter-Archive and Roundtable tables — both features are gone

Revision ID: 0018_drop_removed_feature_tables
Revises: 0017_file_chunks
Create Date: 2026-08-08

Nine tables outlived the features that wrote them.

The Counter-Archive engine (Ghost Layer / Figures / Gaps / Detritus /
Sessions / Counterfactuals, grounded in Glissant, Hartman and Azoulay) was
removed; `api/services/catalog/` no longer contains any of its passes or
prompt modules. The Roundtable multi-agent orchestrator and its ten
archival-theory agents were removed in `682931a`. In both cases the code went
and the schema stayed, because a table is only deleted by someone deliberately
choosing to delete it.

Verified before writing this: nothing in `api/services`, `api/routes` or
`web/src` reads any of the nine. The only surviving mentions were two prose
references — one comment in `catalog/wikilinks.py` citing `ca_gaps` as a
pattern to imitate, and a line in the maintainer notes documenting
`ca_potentials.draft_path` — both removed in the same change as this.

Indexes are not dropped explicitly: SQLite drops a table's indexes with the
table, and every index here belongs to one of these tables (`idx_ca_*`,
`idx_rt_*`).

On downgrade, see the note there — this one does not round-trip, on purpose.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018_drop_removed_feature_tables"
down_revision: Union[str, None] = "0017_file_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Order matters: children before parents. `ca_interactions` references
# `ca_sessions`, and `roundtable_posts` references `roundtable_sessions`, both
# with REFERENCES clauses. Dropping the parent first would fail on any database
# with `PRAGMA foreign_keys=ON`.
_TABLES = (
    "ca_interactions",
    "ca_sessions",
    "ca_detritus",
    "ca_potentials",
    "ca_gaps",
    "ca_ghosts",
    "ca_figures",
    "roundtable_posts",
    "roundtable_sessions",
)


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript("\n".join(f"DROP TABLE IF EXISTS {name};" for name in _TABLES))


def downgrade() -> None:
    """Deliberately a no-op.

    A downgrade could only recreate empty shells. The schemas live in 0005,
    0006, 0007, 0010 and 0011 and are recoverable from there if a
    Counter-Archive or Roundtable revival ever needs them, but re-emitting
    them here would produce tables that no code reads, cannot be repopulated,
    and would be dropped again by the next upgrade — the appearance of
    reversibility without the substance.

    The rows themselves are not recoverable by any downgrade; that is what
    dropping a table means, and it is the point of this migration.
    """
