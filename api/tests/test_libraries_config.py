"""Tests for services/libraries_config.py — the libraries.conf <-> override.yml writer."""

import pytest
from pathlib import Path

from services import libraries_config as lc


@pytest.fixture
def tmp_conf(tmp_path, monkeypatch):
    """Redirect both files to a tmp dir per test (parallel-safe)."""
    conf = tmp_path / "libraries.conf"
    override = tmp_path / "docker-compose.override.yml"
    monkeypatch.setenv("LIBRARIES_CONFIG_PATH", str(conf))
    monkeypatch.setenv("DOCKER_OVERRIDE_PATH", str(override))
    return conf, override


def test_read_entries_missing_file_returns_empty(tmp_conf):
    conf, _ = tmp_conf
    assert not conf.exists()
    assert lc.read_entries() == {}


def test_read_entries_parses_simple_lines(tmp_conf):
    conf, _ = tmp_conf
    conf.write_text("books = /Volumes/Books\npapers = /home/me/papers\n")
    assert lc.read_entries() == {
        "books": "/Volumes/Books",
        "papers": "/home/me/papers",
    }


def test_read_entries_skips_comments_and_blank_lines(tmp_conf):
    conf, _ = tmp_conf
    conf.write_text(
        "# header comment\n"
        "\n"
        "books = /Volumes/Books\n"
        "   # indented comment\n"
        "\n"
        "papers = /home/me/papers\n"
    )
    assert lc.read_entries() == {
        "books": "/Volumes/Books",
        "papers": "/home/me/papers",
    }


def test_read_entries_skips_malformed_lines(tmp_conf):
    conf, _ = tmp_conf
    conf.write_text(
        "books = /Volumes/Books\n"
        "this line has no equals sign\n"
        "name with spaces = /x\n"  # invalid name
        "papers = /home/me/papers\n"
    )
    assert lc.read_entries() == {
        "books": "/Volumes/Books",
        "papers": "/home/me/papers",
    }


def test_add_entry_creates_new(tmp_conf):
    conf, _ = tmp_conf
    lc.add_entry("books", "/Volumes/Books")
    assert conf.exists()
    assert lc.read_entries() == {"books": "/Volumes/Books"}


def test_add_entry_replaces_existing(tmp_conf):
    lc.add_entry("books", "/old/path")
    lc.add_entry("books", "/new/path")
    assert lc.read_entries() == {"books": "/new/path"}


def test_add_entry_appends_to_existing_entries(tmp_conf):
    lc.add_entry("books", "/Volumes/Books")
    lc.add_entry("papers", "/home/me/papers")
    assert lc.read_entries() == {
        "books": "/Volumes/Books",
        "papers": "/home/me/papers",
    }


def test_add_entry_rejects_invalid_name(tmp_conf):
    with pytest.raises(ValueError, match="alphanumeric"):
        lc.add_entry("name with spaces", "/x")
    with pytest.raises(ValueError, match="alphanumeric"):
        lc.add_entry("name/with/slash", "/x")
    with pytest.raises(ValueError, match="alphanumeric"):
        lc.add_entry("", "/x")


def test_add_entry_rejects_relative_path(tmp_conf):
    with pytest.raises(ValueError, match="absolute"):
        lc.add_entry("books", "relative/path")
    with pytest.raises(ValueError, match="absolute"):
        lc.add_entry("books", "")


def test_remove_entry_returns_true_when_found(tmp_conf):
    lc.add_entry("books", "/Volumes/Books")
    lc.add_entry("papers", "/home/me/papers")
    assert lc.remove_entry("books") is True
    assert lc.read_entries() == {"papers": "/home/me/papers"}


def test_remove_entry_returns_false_when_absent(tmp_conf):
    lc.add_entry("papers", "/home/me/papers")
    assert lc.remove_entry("books") is False
    assert lc.read_entries() == {"papers": "/home/me/papers"}


def test_remove_entry_from_empty_file_returns_false(tmp_conf):
    assert lc.remove_entry("anything") is False


def test_regenerate_override_zero_entries_empties_but_keeps_file(tmp_conf):
    """Zero entries truncates the override to an inert file — it does NOT
    unlink it.

    The file is bind-mounted from the host (docker-compose.yml mounts it
    individually so the project root can stay read-only), and a bind-mounted
    file cannot be removed from inside a container: the unlink fails with
    EBUSY. Deleting it here would also mean the next `docker compose up` finds
    no source for the mount, and Docker answers a missing bind-mount source by
    creating a DIRECTORY — which compose then tries to parse as YAML.
    """
    _, override = tmp_conf
    override.write_text("services:\n  api:\n    volumes:\n      - /x:/y:ro\n")
    result = lc.regenerate_override()

    assert override.exists(), "the override must survive as a file"
    assert result == override
    text = override.read_text()
    assert "volumes:" not in text, "stale mounts must be gone"
    assert text.lstrip().startswith("#"), "what remains must be inert"


def test_regenerate_override_zero_entries_creates_file_when_missing(tmp_conf):
    """Even with nothing configured and no file present, one is written.

    Same reason: the path has to exist before the stack starts.
    """
    _, override = tmp_conf
    assert not override.exists()
    result = lc.regenerate_override()
    assert override.exists()
    assert result == override


def test_inert_override_is_accepted_by_a_yaml_parser(tmp_conf):
    """The inert file must still be loadable as a compose fragment.

    A comment-only document parses to None rather than a mapping, which is
    fine for compose but is the sort of thing that quietly stops being true if
    someone edits the template.
    """
    import yaml

    _, override = tmp_conf
    lc.regenerate_override()
    assert yaml.safe_load(override.read_text()) is None


def test_regenerate_override_single_entry(tmp_conf):
    _, override = tmp_conf
    lc.add_entry("books", "/Volumes/Books")
    lc.regenerate_override()
    text = override.read_text()
    assert "services:" in text
    assert "  api:" in text
    assert "/Volumes/Books:/libraries/books:ro" in text
    # Exactly one block. There used to be a second for `worker`, but that
    # service was folded into the api (2026-08-18) — emitting a block for a
    # service that no longer exists makes compose build an image-less service
    # and fail the whole stack, rather than being harmlessly ignored.
    assert "  worker:" not in text
    assert text.count("/Volumes/Books:/libraries/books:ro") == 1


def test_regenerate_override_two_entries(tmp_conf):
    _, override = tmp_conf
    lc.add_entry("books", "/Volumes/Books")
    lc.add_entry("papers", "/home/me/papers")
    lc.regenerate_override()
    text = override.read_text()
    assert text.count("/Volumes/Books:/libraries/books:ro") == 1
    assert text.count("/home/me/papers:/libraries/papers:ro") == 1
    # YAML structure intact
    assert text.startswith("# Auto-generated")
    assert "services:\n  api:\n    volumes:\n" in text
    assert "  worker:" not in text


def test_add_then_regenerate_roundtrip(tmp_conf):
    _, override = tmp_conf
    lc.add_entry("books", "/Volumes/Books")
    lc.regenerate_override()
    assert override.exists()
    lc.remove_entry("books")
    lc.regenerate_override()
    # Emptied, not deleted — see test_regenerate_override_zero_entries_*.
    assert override.exists()
    assert "/Volumes/Books" not in override.read_text()


def test_write_is_atomic_no_tmp_left_behind(tmp_conf):
    conf, _ = tmp_conf
    lc.add_entry("books", "/Volumes/Books")
    tmp = conf.with_suffix(conf.suffix + ".tmp")
    assert not tmp.exists()


def test_write_falls_back_to_in_place_when_the_parent_is_read_only(
    tmp_conf, monkeypatch
):
    """The write must still land when a `.tmp` sibling cannot be created.

    This is the api container's actual situation and it is not hypothetical:
    docker-compose.yml bind-mounts libraries.conf and the override as
    individual files inside a read-only project root, so creating the sibling
    fails with EROFS. Before the fallback existed, every add/remove from the
    Settings UI raised OSError — verified by running it in the container, which
    is the only reason it was caught.
    """
    conf, _ = tmp_conf

    real_write_text = Path.write_text

    def refuse_tmp(self, *a, **kw):
        if self.name.endswith(".tmp"):
            raise OSError(30, "Read-only file system")
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", refuse_tmp)

    lc.add_entry("books", "/Volumes/Books")
    assert "books = /Volumes/Books" in conf.read_text()
    assert not conf.with_suffix(conf.suffix + ".tmp").exists()


def test_write_falls_back_to_in_place_when_rename_crosses_devices(
    tmp_conf, monkeypatch
):
    """Same, for the other half of the constraint.

    A bind-mounted file is its own device, so `os.replace` onto it fails with
    EXDEV even when the `.tmp` was created successfully. The fallback writes in
    place and cleans up the tmp it did manage to make.
    """
    conf, _ = tmp_conf

    def refuse_replace(*a, **kw):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(lc.os, "replace", refuse_replace)

    lc.add_entry("books", "/Volumes/Books")
    assert "books = /Volumes/Books" in conf.read_text()
    assert not conf.with_suffix(conf.suffix + ".tmp").exists(), "tmp must be cleaned up"


def test_validate_name_allows_hyphens_and_underscores(tmp_conf):
    lc.validate_name("my-lib_2")  # no raise
    lc.validate_name("ABC")  # no raise


def test_validate_name_rejects_dots_slashes_spaces(tmp_conf):
    for bad in ("a.b", "a/b", "a b", "a:b", ""):
        with pytest.raises(ValueError):
            lc.validate_name(bad)


# --- host_path hardening (code audit 2026-11-20 H2) -------------------------
# The path lands in `- <path>:/libraries/<name>:ro`. Anything that changes how
# compose splits that string, or how YAML reads it, can turn a library mount
# into a read-write bind mount of the host root.

_HOSTILE_PATHS = [
    "/:/hostroot:rw #",
    "/x:/y",
    "/x # comment",
    "/x#y",
    '/x"y',
    "/x'y",
    "/x\nevil = /:/h",
    "/x\r/y",
    "/x\ty",
    "/x\x00y",
    " /x",
    "/x ",
    "/",
    "relative/path",
    "",
]


@pytest.mark.parametrize("bad", _HOSTILE_PATHS)
def test_validate_host_path_rejects_hostile_paths(bad):
    with pytest.raises(ValueError):
        lc.validate_host_path(bad)


@pytest.mark.parametrize("bad", _HOSTILE_PATHS)
def test_add_entry_rejects_hostile_paths_and_writes_nothing(tmp_conf, bad):
    conf, override = tmp_conf
    with pytest.raises(ValueError):
        lc.add_entry("evil", bad)
    assert not conf.exists()
    assert not override.exists()


def test_validate_host_path_allows_ordinary_paths():
    for ok in ("/Volumes/Books", "/home/me/My Books", "/mnt/data-1/lib_2.0"):
        lc.validate_host_path(ok)


def test_override_for_a_path_with_a_space_is_one_exact_volume(tmp_conf):
    import yaml

    _, override = tmp_conf
    lc.add_entry("books", "/home/me/My Books")
    lc.regenerate_override()
    doc = yaml.safe_load(override.read_text())
    assert doc["services"]["api"]["volumes"] == [
        "/home/me/My Books:/libraries/books:ro"
    ]


def test_regenerate_skips_a_hand_edited_hostile_entry(tmp_conf):
    """libraries.conf can be hand-edited, so the renderer cannot trust it."""
    import yaml

    conf, override = tmp_conf
    conf.write_text("evil = /:/hostroot:rw #\nbooks = /Volumes/Books\n")
    lc.regenerate_override()
    doc = yaml.safe_load(override.read_text())
    assert doc["services"]["api"]["volumes"] == ["/Volumes/Books:/libraries/books:ro"]
