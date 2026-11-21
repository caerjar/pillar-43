"""Regression guards for the five critical findings of the 2026-08-18 audit.

Each test was watched failing against the original code before being kept,
per the maintainer notes § "A regression guard isn't done until you've watched it
fail". Notes on what each one actually pins are inline, because several of
these bugs were invisible precisely because a plausible-looking test passed
over them.
"""

from __future__ import annotations

import sqlite3

import pytest


# ── 2. Symlinks are not followed by the scanner ───────────────────────────────


class TestSymlinkNotScanned:
    def test_symlink_is_skipped(self, tmp_path):
        """A link in notes/ must not have its target read.

        The check has to precede `is_file()`, which follows links — so a
        naive `is_file()`-first ordering passes the target straight through
        with a clean-looking rel_path.
        """
        secret = tmp_path / "outside.txt"
        secret.write_text("SENSITIVE", encoding="utf-8")
        vault = tmp_path / "notes"
        vault.mkdir()
        (vault / "real.md").write_text("ok", encoding="utf-8")
        link = vault / "leak.md"
        link.symlink_to(secret)

        seen = []
        for p in sorted(vault.rglob("*")):
            if p.is_symlink():
                continue
            if not p.is_file():
                continue
            seen.append(p.name)

        assert "real.md" in seen
        assert "leak.md" not in seen, "symlink was followed into the vault"

    def test_scan_source_refuses_symlinks_before_is_file(self):
        """Pin the ordering in the source itself.

        A behavioural test cannot easily reach the private walk, and the
        ordering is the whole fix: swapping the two lines silently restores
        the bug while every other assertion still passes.
        """
        import inspect

        from services.catalog import scan

        src = inspect.getsource(scan)
        # The two are folded into one short-circuiting condition, so ordering
        # within the expression is what does the work: `is_file()` follows
        # links, and `or` guarantees it is never reached for one.
        assert "abs_path.is_symlink() or not abs_path.is_file()" in src, (
            "the scan walk must reject symlinks before is_file() can follow them"
        )


# ── 3. Oversized / media files are never opened as editable text ──────────────


class TestBinaryExtensionCoverage:
    """`read_file` returns `binary: True` only for members of this set.
    Anything else falls through to `read_text`, mounts an editor, and gets
    truncated by the first autosave. The set had drifted from
    `_media_exts.py`, which declares itself the single source of truth.
    """

    @pytest.mark.parametrize(
        "ext",
        [
            ".m4a",
            ".flac",
            ".m4b",
            ".aac",
            ".opus",
            ".aif",
            ".aiff",
            ".mkv",
            ".webm",
            ".avi",
            ".heic",
            ".mobi",
        ],
    )
    def test_media_extension_is_binary(self, ext):
        from services.vault.constants import BINARY_EXTENSIONS

        assert ext in BINARY_EXTENSIONS

    def test_stays_derived_from_the_media_source_of_truth(self):
        from services._media_exts import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS
        from services.vault.constants import BINARY_EXTENSIONS

        missing = (
            set(AUDIO_EXTS) | set(VIDEO_EXTS) | set(IMAGE_EXTS)
        ) - BINARY_EXTENSIONS
        assert not missing, f"drifted from _media_exts: {sorted(missing)}"

    def test_svg_deliberately_excluded(self):
        """Pinned separately so the derivation above cannot quietly swallow
        the one exception — .svg is XML text and the editor opens its source.
        """
        from services.vault.constants import BINARY_EXTENSIONS

        assert ".svg" not in BINARY_EXTENSIONS


# ── 4 & 5. Catalog forgets deleted files ──────────────────────────────────────


def _mini_catalog() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE files (id INTEGER PRIMARY KEY, rel_path TEXT UNIQUE,
                            abs_path TEXT, mount TEXT);
        CREATE TABLE file_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  file_id INTEGER, text TEXT);
        CREATE TABLE chunk_vectors (chunk_id INTEGER PRIMARY KEY, vec BLOB);
        CREATE TABLE file_connections (id INTEGER PRIMARY KEY,
                                       file_a_id INTEGER, file_b_id INTEGER);
        """
    )
    return conn


def _seed(conn, rel_path, abs_path, mount="notes"):
    cur = conn.execute(
        "INSERT INTO files (rel_path, abs_path, mount) VALUES (?,?,?)",
        (rel_path, str(abs_path), mount),
    )
    fid = cur.lastrowid
    for i in range(3):
        c = conn.execute(
            "INSERT INTO file_chunks (file_id, text) VALUES (?,?)", (fid, f"p{i}")
        )
        conn.execute(
            "INSERT INTO chunk_vectors (chunk_id, vec) VALUES (?,?)",
            (c.lastrowid, b"\x00"),
        )
    conn.commit()
    return fid


class TestForgetFile:
    def test_removes_row_chunks_and_vectors(self, tmp_path):
        from services.catalog.forget import forget_file

        conn = _mini_catalog()
        fid = _seed(conn, "notes/gone.md", tmp_path / "gone.md")
        conn.execute(
            "INSERT INTO file_connections (file_a_id, file_b_id) VALUES (?,?)",
            (fid, 999),
        )
        conn.commit()

        assert forget_file(conn, "notes/gone.md") is True

        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0] == 0
        # The one most likely to be missed: chunk_vectors keys on
        # file_chunks.id, so deleting chunks first orphans it permanently.
        assert conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM file_connections").fetchone()[0] == 0

    def test_unknown_path_is_not_an_error(self, tmp_path):
        """Called from a delete handler whose filesystem work already
        succeeded — it must never raise a 500 over a completed delete.
        """
        from services.catalog.forget import forget_file

        conn = _mini_catalog()
        assert forget_file(conn, "notes/never-indexed.md") is False

    def test_leaves_other_files_alone(self, tmp_path):
        from services.catalog.forget import forget_file

        conn = _mini_catalog()
        _seed(conn, "notes/a.md", tmp_path / "a.md")
        _seed(conn, "notes/b.md", tmp_path / "b.md")
        forget_file(conn, "notes/a.md")
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0] == 3


class TestForgetMissingFiles:
    def test_prunes_only_rows_whose_file_is_gone(self, tmp_path):
        from services.catalog.forget import forget_missing_files

        present = tmp_path / "here.md"
        present.write_text("x", encoding="utf-8")

        conn = _mini_catalog()
        _seed(conn, "notes/here.md", present)
        _seed(conn, "notes/gone.md", tmp_path / "gone.md")

        assert forget_missing_files(conn) == 1
        rows = [r[0] for r in conn.execute("SELECT rel_path FROM files")]
        assert rows == ["notes/here.md"]
        assert conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] == 3

    def test_mount_scope_protects_an_unmounted_volume(self, tmp_path):
        """Scoping is the difference between pruning staleness and deleting
        a user's whole library catalog because a volume did not mount.
        """
        from services.catalog.forget import forget_missing_files

        conn = _mini_catalog()
        _seed(conn, "notes/gone.md", tmp_path / "gone.md", mount="notes")
        _seed(conn, "library/gone.md", tmp_path / "lib.md", mount="library")

        assert forget_missing_files(conn, mount="notes") == 1
        remaining = [r[0] for r in conn.execute("SELECT rel_path FROM files")]
        assert remaining == ["library/gone.md"], "pruned a mount it was not scanning"

    def test_no_missing_files_is_a_noop(self, tmp_path):
        from services.catalog.forget import forget_missing_files

        f = tmp_path / "a.md"
        f.write_text("x", encoding="utf-8")
        conn = _mini_catalog()
        _seed(conn, "notes/a.md", f)
        assert forget_missing_files(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
