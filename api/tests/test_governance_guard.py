"""The shell guards that stop `./pillar43 reset` and `make clean` from deleting
the governance state (scripts/governance.sh). No Docker: `docker` is a stub on
PATH and the live state comes from GOVERNANCE_STATE_CMD."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = (
    Path("/repo")
    if Path("/repo/pillar43").exists()
    else Path(__file__).resolve().parents[2]
)
pytestmark = pytest.mark.skipif(
    not (REPO / "scripts" / "governance.sh").exists(), reason="repo scripts not mounted"
)

STATE_5 = "ledger_seq=5\nitems=3\ntombstones=1\naccounts=1\n"
STATE_EMPTY = "ledger_seq=0\nitems=0\ntombstones=0\naccounts=0\n"


@pytest.fixture
def tree(tmp_path):
    """A copy of the launcher + scripts, a stub docker, a backup folder."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for rel in ("pillar43", "scripts/governance.sh", "scripts/ensure-host-files.sh"):
        shutil.copy(REPO / rel, root / rel)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "docker.log"
    stub = bin_ / "docker"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    stub.chmod(0o755)
    (root / ".env").write_text("")
    backups = tmp_path / "backups"
    backups.mkdir()
    return root, backups, log, bin_


def run(tree, args, state=STATE_5, **extra_env):
    root, backups, _log, bin_ = tree
    env = {
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "PILLAR43_BACKUP_DIR": str(backups),
        "GOVERNANCE_STATE_CMD": f"printf '{state}'",
        "HOME": str(root),
        **extra_env,
    }
    return subprocess.run(
        args,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def check(tree, state=STATE_5, **env):
    return run(tree, ["bash", "scripts/governance.sh", "check"], state, **env)


def test_no_backup_refuses_and_says_what_is_lost(tree):
    r = check(tree)
    assert r.returncode == 1
    assert "Refusing" in r.stderr
    assert "5 ledger line(s)" in r.stderr and "3 item(s)" in r.stderr
    assert "1 withdrawal(s)" in r.stderr and "1 account(s)" in r.stderr
    assert "No backup found" in r.stderr


def test_stale_backup_refuses(tree):
    (tree[1] / "governance-pillar43-20261121T100000Z-seq4.sqlite").write_bytes(b"x")
    r = check(tree)
    assert r.returncode == 1 and "4 ledger line(s); the archive has 5" in r.stderr


def test_backup_covering_the_ledger_passes(tree):
    (tree[1] / "governance-pillar43-20261121T100000Z-seq5.sqlite").write_bytes(b"x")
    assert check(tree).returncode == 0


def test_backup_of_another_project_does_not_count(tree):
    (tree[1] / "governance-other-20261121T100000Z-seq9.sqlite").write_bytes(b"x")
    assert check(tree).returncode == 1


def test_newest_backup_by_time_is_the_one_compared(tree):
    (tree[1] / "governance-pillar43-20261121T100000Z-seq9.sqlite").write_bytes(b"x")
    (tree[1] / "governance-pillar43-20261122T100000Z-seq2.sqlite").write_bytes(b"x")
    assert check(tree).returncode == 1


def test_explicit_confirm_lets_it_pass(tree):
    assert check(tree, CONFIRM_DATA_LOSS="yes").returncode == 0
    assert check(tree, CONFIRM_DATA_LOSS="please").returncode == 1


def test_empty_archive_has_nothing_to_lose(tree):
    assert check(tree, state=STATE_EMPTY).returncode == 0


def test_unreadable_state_refuses(tree):
    r = check(tree, GOVERNANCE_STATE_CMD="exit 3")
    assert r.returncode == 1 and "cannot read the records" in r.stderr
    assert (
        check(tree, GOVERNANCE_STATE_CMD="exit 3", CONFIRM_DATA_LOSS="yes").returncode
        == 0
    )


@pytest.mark.parametrize("flags", [["reset", "--hard"], ["reset"]])
def test_pillar43_reset_refuses_before_touching_docker(tree, flags):
    r = run(tree, ["bash", "pillar43", *flags])
    assert r.returncode == 1
    assert "Refusing" in r.stderr
    log = tree[2].read_text() if tree[2].exists() else ""
    assert "down" not in log and "volume rm" not in log


def test_pillar43_reset_gets_past_the_guard_with_a_backup(tree):
    (tree[1] / "governance-pillar43-20261121T100000Z-seq5.sqlite").write_bytes(b"x")
    r = run(tree, ["bash", "pillar43", "reset", "--hard"])
    assert "Refusing" not in r.stderr
    assert "Type YES" in r.stdout  # reached the existing confirmation
    log = tree[2].read_text() if tree[2].exists() else ""
    assert "down -v" not in log  # no tty, so the YES prompt stopped it


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed here")
def test_make_clean_refuses(tree):
    root = tree[0]
    shutil.copy(REPO / "Makefile", root / "Makefile")
    r = run(tree, ["make", "clean"])
    assert r.returncode != 0 and "Refusing" in r.stderr
    log = tree[2].read_text() if tree[2].exists() else ""
    assert "down -v" not in log


@pytest.mark.parametrize(
    "state",
    [
        "ledger_seq=0\nitems=2\ntombstones=0\naccounts=0\n",
        "ledger_seq=0\nitems=0\ntombstones=1\naccounts=0\n",
        "ledger_seq=0\nitems=0\ntombstones=0\naccounts=1\n",
    ],
)
def test_any_governance_row_counts_as_something_to_lose(tree, state):
    assert check(tree, state=state).returncode == 1


def _fake_api(tree):
    """A docker stub that behaves like the archive CLI: `backup -` writes bytes,
    `backup-check -` reads them and reports the ledger length."""
    stub = tree[3] / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"archive_cli.py backup -"*) printf "SQLITE-BYTES" ;;\n'
        '  *"archive_cli.py backup-check -"*) cat >/dev/null; echo "ledger_seq=7" ;;\n'
        "esac\n"
    )
    stub.chmod(0o755)


def test_backup_with_no_dest_lands_in_the_backup_folder_named_by_ledger_length(tree):
    _fake_api(tree)
    shutil.rmtree(tree[1])  # the folder does not exist yet on a first backup
    r = run(tree, ["bash", "scripts/governance.sh", "backup"])
    assert r.returncode == 0, r.stderr
    files = list(tree[1].glob("governance-pillar43-*-seq7.sqlite"))
    assert len(files) == 1 and files[0].read_bytes() == b"SQLITE-BYTES"
    # and the guard now accepts exactly that file
    assert (
        check(
            tree, state="ledger_seq=7\nitems=1\ntombstones=0\naccounts=0\n"
        ).returncode
        == 0
    )


def test_backup_to_an_explicit_file_and_a_failed_verify_keeps_nothing(tree, tmp_path):
    _fake_api(tree)
    dest = tmp_path / "drive" / "mine.sqlite"
    assert (
        run(tree, ["bash", "scripts/governance.sh", "backup", str(dest)]).returncode
        == 0
    )
    assert dest.read_bytes() == b"SQLITE-BYTES"
    (tree[3] / "docker").write_text(
        '#!/bin/sh\ncase "$*" in *"backup -"*) printf X ;; *) exit 1 ;; esac\n'
    )
    bad = tmp_path / "drive" / "bad.sqlite"
    r = run(tree, ["bash", "scripts/governance.sh", "backup", str(bad)])
    assert r.returncode != 0 and not bad.exists()
