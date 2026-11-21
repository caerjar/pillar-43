"""Remove a file from the catalog when it leaves the vault.

Nothing did this before. `DELETE FROM files` appeared nowhere in `routes/`
or `services/`: trashing moved bytes on disk, deleting unlinked them, and
the scan had no prune step — so a row survived every way a file can leave.

That is a correctness bug, not a disk leak. The orphans are not dangling
FK references; they are live, joinable rows. They pass the inner join in
`vector_store._load_matrix`, so semantic search returns them; `files_fts`
still holds their text, so lexical search returns them; and
`retrieval.fetch_materials` — the shared chokepoint feeding the AI sidebar
and the Commons bot — quotes them back at the user. Measured on the
development vault the day this was written: 130 of 357 rows (36%) pointed
at paths that no longer existed, carrying 1,089 chunks and 1,089 vectors.

Order matters. `chunk_vectors` is keyed on `file_chunks.id`, so it must go
first or its rows become unreachable; `PRAGMA foreign_keys` is off on
these connections, so the `ON DELETE CASCADE` declared in migration 0021
never fires and every delete here has to be explicit. `files_fts` is
maintained by triggers and is deliberately NOT touched — the DELETE
trigger on `files` handles it, and doing it by hand would double-delete.
"""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)


def forget_file(conn: sqlite3.Connection, rel_path: str) -> bool:
    """Drop every catalog row for `rel_path`. True if a row was removed.

    Safe to call for a path that was never catalogued — that is the common
    case for a vault where indexing has not run, and it must not raise into
    a delete handler whose filesystem work already succeeded.
    """
    row = conn.execute(
        "SELECT id FROM files WHERE rel_path = ?", (rel_path,)
    ).fetchone()
    if row is None:
        return False
    file_id = row[0]

    with conn:
        conn.execute(
            "DELETE FROM chunk_vectors WHERE chunk_id IN "
            "(SELECT id FROM file_chunks WHERE file_id = ?)",
            (file_id,),
        )
        conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
        conn.execute(
            "DELETE FROM file_connections WHERE file_a_id = ? OR file_b_id = ?",
            (file_id, file_id),
        )
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    return True


def forget_missing_files(conn: sqlite3.Connection, *, mount: str | None = None) -> int:
    """Prune rows whose `abs_path` no longer exists. Returns the count.

    The backstop for every route that does not call `forget_file` — a file
    removed outside the app, a mount unplugged, or any handler written
    before this module existed. Runs at the end of a scan, where the walk
    has already paid for the directory reads.

    Scoped to `mount` when given: a scan of `notes/` must not prune
    `library/` rows just because that mount happens to be offline. Deleting
    a user's whole catalog because a volume did not mount is a worse
    failure than the staleness this fixes.
    """
    from pathlib import Path

    if mount:
        rows = conn.execute(
            "SELECT id, abs_path FROM files WHERE mount = ?", (mount,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, abs_path FROM files").fetchall()

    gone = [r[0] for r in rows if r[1] and not Path(r[1]).exists()]
    if not gone:
        return 0

    placeholders = ",".join("?" * len(gone))
    with conn:
        conn.execute(
            f"DELETE FROM chunk_vectors WHERE chunk_id IN "
            f"(SELECT id FROM file_chunks WHERE file_id IN ({placeholders}))",
            gone,
        )
        conn.execute(f"DELETE FROM file_chunks WHERE file_id IN ({placeholders})", gone)
        conn.execute(
            f"DELETE FROM file_connections WHERE file_a_id IN ({placeholders}) "
            f"OR file_b_id IN ({placeholders})",
            gone + gone,
        )
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", gone)

    log.info(
        "[catalog] pruned %d catalog rows for files that no longer exist", len(gone)
    )
    return len(gone)
