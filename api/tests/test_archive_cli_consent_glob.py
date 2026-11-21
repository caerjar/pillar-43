"""`archive_cli consent glob:PATTERN` opens the items whose path matches, and
only those: `make archive` uses it for the yellow thread, and the letter closed
by its writer must stay closed."""

from __future__ import annotations

from services.db import get_db
from tests import archive_fixtures as fx

OPEN = "library/design/yellow-spine-brief_2019-03-12.md"
OPEN_LETTER = (
    "library/correspondence/letters/2022-09-19_wenlock_harbour-jacket-yellow.txt"
)
CLOSED = "library/correspondence/letters/2024-05-06_merrowby_spine-colour.txt"


def test_glob_opens_matching_paths_and_leaves_the_rest(tmp_path, monkeypatch):
    from scripts import archive_cli

    fx.settings(tmp_path, monkeypatch)
    fx.seed(OPEN, "yellow", "staff", kind="design")
    fx.seed(OPEN_LETTER, "yellow", "private", kind="letter")
    fx.seed(CLOSED, "yellow band", "private", kind="letter")

    assert archive_cli.consent("glob:*YELLOW*", "model", "setup") == 2

    conn = get_db()
    try:
        levels = dict(conn.execute("SELECT path, consent FROM item"))
    finally:
        conn.close()
    assert levels == {OPEN: "model", OPEN_LETTER: "model", CLOSED: "private"}
