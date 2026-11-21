"""Tests for the scan loop's skip policy.

`_skip_reason` was six consecutive `if …: continue` guards inside a 342-line
function, reachable only through a full catalog run. Extracted as a pure
predicate so the policy can be asserted directly — including the one guard
that is a security control rather than a performance one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.catalog.scan import _skip_reason


def _parts(rel: str) -> tuple[str, ...]:
    return tuple(rel.split("/"))


def test_an_ordinary_note_is_not_skipped():
    assert (
        _skip_reason(Path("/v/notes/a.md"), mount="notes", rel_parts=_parts("a.md"))
        is None
    )


def test_commons_content_under_generated_is_never_scanned():
    """A security control, not an optimisation.

    generated/commons/** is untrusted remote content — wire logs and
    downloaded attachments. Scanning it would feed an attacker's document to
    a parser and let it poison the search index. See the maintainer notes.
    """
    assert (
        _skip_reason(
            Path("/v/generated/commons/x/posts.md"),
            mount="generated",
            rel_parts=_parts("commons/x/posts.md"),
        )
        == "untrusted-commons-content"
    )


def test_commons_named_directory_elsewhere_is_still_scanned():
    """The guard is scoped to generated/ — a user's own notes/commons/ is theirs."""
    assert (
        _skip_reason(
            Path("/v/notes/commons/mine.md"),
            mount="notes",
            rel_parts=_parts("commons/mine.md"),
        )
        is None
    )


@pytest.mark.parametrize(
    "rel,expected",
    [
        (".hidden/x.md", "excluded-directory"),
        ("node_modules/x.md", "excluded-directory"),
        ("sub/.git/x.md", "excluded-directory"),
    ],
)
def test_excluded_directories(rel, expected):
    assert (
        _skip_reason(Path("/v/notes/" + rel), mount="notes", rel_parts=_parts(rel))
        == expected
    )


def test_dotfiles_are_skipped():
    assert (
        _skip_reason(
            Path("/v/notes/.DS_Store"), mount="notes", rel_parts=_parts(".DS_Store")
        )
        == "excluded-file"
    )


def test_code_config_extensions_are_skipped():
    assert (
        _skip_reason(
            Path("/v/notes/main.py"), mount="notes", rel_parts=_parts("main.py")
        )
        == "code-config-extension"
    )


def test_a_directory_named_like_a_file_is_judged_by_its_parts():
    """rel_parts[:-1] — the final component is the file, not a directory."""
    assert (
        _skip_reason(
            Path("/v/notes/node_modules.md"),
            mount="notes",
            rel_parts=_parts("node_modules.md"),
        )
        is None
    )


def test_the_reason_is_stable_enough_to_report():
    """Returning a reason rather than a bool means a future "why was my file
    skipped?" surface has something to say. Keep them machine-readable."""
    r = _skip_reason(Path("/v/notes/.x"), mount="notes", rel_parts=_parts(".x"))
    assert r and " " not in r
