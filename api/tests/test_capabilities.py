"""Tests for the external-binary capability layer and git degradation.

These exist because of a measured failure, not a hypothetical one. Booting the
API with `git` off `PATH` (2026-08-17) produced two distinct bugs:

  1. `POST /api/library/init` — the first-run wizard's own workspace step —
     returned a bare 500 from an uncaught `FileNotFoundError`.
  2. Vault writes returned 201 and landed on disk, but the batched committer
     failed on a background thread and swallowed the error, so version history
     silently never recorded anything.

A third fell out of fixing those: `git_ready` gates the wizard on `notes/.git`
existing, which on a git-less machine is unreachable, so the wizard would
reappear after every completed setup.

Every test here simulates git's absence by patching `shutil.which` inside
`services.capabilities` — none of them require (or forbid) a real git binary,
which is why the module is not marked `integration`.
"""

import shutil
import subprocess

import pytest
from httpx import AsyncClient, ASGITransport

from config import settings
from main import app
from services import capabilities


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    """Probes are cached process-wide; a stale entry would leak between tests."""
    capabilities.reset_cache()
    yield
    capabilities.reset_cache()


@pytest.fixture
def no_git(monkeypatch):
    """Make `git` genuinely absent, while leaving every other binary alone.

    Patching only `shutil.which` is not enough and the difference matters. The
    test container HAS git, so a probe-only fake still lets every real git
    subprocess succeed — which means a test written that way passes even with
    the guard removed. It would certify the bug rather than catch it. (Found
    exactly that way: deleting the `ensure_repo` guard left
    `test_library_init_succeeds_without_git` green.)

    So patch both halves: the probe reports absent, AND any `git` subprocess
    raises `FileNotFoundError` the way a missing binary really does. Non-git
    commands (`rg`, `ffmpeg`) delegate to the real implementations, since these
    tests must not disturb anything else.
    """
    real_which = shutil.which
    real_run = subprocess.run

    def fake_which(name, *a, **kw):
        return None if name == "git" else real_which(name, *a, **kw)

    def fake_run(cmd, *a, **kw):
        argv0 = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        if argv0 == "git":
            raise FileNotFoundError(2, "No such file or directory: 'git'")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(capabilities.shutil, "which", fake_which)
    # Patched on the shared module object, so every `import subprocess;
    # subprocess.run(...)` call site sees it.
    monkeypatch.setattr(subprocess, "run", fake_run)
    capabilities.reset_cache()
    return fake_which


@pytest.fixture
def notes_root(tmp_path, monkeypatch):
    active = tmp_path / "notes"
    generated = tmp_path / "generated"
    active.mkdir()
    generated.mkdir()
    monkeypatch.setattr(settings, "notes_path", active)
    monkeypatch.setattr(settings, "generated_path", generated)
    return active


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── the capability report ────────────────────────────────────────────────────


def test_report_covers_every_known_binary():
    assert set(capabilities.report()) == {
        "git",
        "ripgrep",
        "ffmpeg",
        "ffprobe",
    }


def test_report_entry_explains_the_degradation():
    entry = capabilities.report()["git"]
    assert entry["binary"] == "git"
    # The point of the layer is that a user can tell what they lose.
    assert entry["degraded"]
    assert entry["remedy"]


def test_missing_names_the_absent_binary(no_git):
    assert capabilities.missing() == ["git"]
    assert capabilities.git_available() is False


def test_probe_is_cached(monkeypatch):
    calls = []
    real_which = shutil.which

    def counting_which(name, *a, **kw):
        calls.append(name)
        return real_which(name, *a, **kw)

    monkeypatch.setattr(capabilities.shutil, "which", counting_which)
    capabilities.reset_cache()

    capabilities.git_available()
    capabilities.git_available()
    capabilities.git_available()

    assert calls.count("git") == 1


# ── the two measured route bugs ──────────────────────────────────────────────


async def test_status_reports_capabilities(client, no_git, notes_root):
    r = await client.get("/api/library/status")
    assert r.json()["capabilities"]["git"]["available"] is False


# ── the no-degraded-form paths: raise, but raise something useful ───────────


@pytest.fixture
def no_binary(monkeypatch):
    """Make an arbitrary named binary absent (and only that one)."""
    real_which = shutil.which

    def make(name):
        def fake_which(n, *a, **kw):
            return None if n == name else real_which(n, *a, **kw)

        monkeypatch.setattr(capabilities.shutil, "which", fake_which)
        capabilities.reset_cache()

    return make


def test_require_names_the_remedy(no_binary):
    no_binary("ffmpeg")
    with pytest.raises(capabilities.CapabilityUnavailableError) as exc:
        capabilities.require("ffmpeg")
    msg = str(exc.value)
    assert "ffmpeg" in msg
    # A user reading this should know what to do about it.
    assert "brew install ffmpeg" in msg


def test_require_is_silent_when_present():
    capabilities.require("ripgrep")  # present in the test image; must not raise


def test_render_pdf_page_needs_no_external_binary(monkeypatch, tmp_path):
    """The desktop bug, inverted into a guard.

    PDF preview was dead in the macOS app because it shelled out to `pdftoppm`,
    which the bundle does not ship and which a Finder-launched app cannot see on
    launchd's PATH. Rendering now goes through PDFium, a wheel, so it must
    succeed with the subprocess machinery entirely unavailable.

    Patching `shutil.which` would NOT do here: the test image really has
    poppler, so a reintroduced `subprocess.run(["pdftoppm", ...])` would still
    succeed and this guard would pass against the exact bug it exists to catch
    (see the maintainer notes on fixtures that fail to simulate absence). Break
    the syscall instead.
    """
    import subprocess

    from PIL import Image

    from services.vault.pdf import render_pdf_page

    pdf = tmp_path / "x.pdf"
    Image.new("RGB", (200, 200), "white").save(pdf, "PDF")

    def boom(*a, **kw):
        raise AssertionError("render_pdf_page shelled out to an external binary")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)

    png = render_pdf_page(pdf, 1, dpi=72)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_pdf_page_rejects_an_out_of_range_page(tmp_path):
    """RuntimeError, not a bare CalledProcessError: routes/files.py maps
    RuntimeError to a 500 carrying the message, and anything else to a generic
    internal error with nothing in it."""
    from PIL import Image

    from services.vault.pdf import render_pdf_page

    pdf = tmp_path / "x.pdf"
    Image.new("RGB", (200, 200), "white").save(pdf, "PDF")

    for bad in (0, 2):
        with pytest.raises(RuntimeError, match="out of range"):
            render_pdf_page(pdf, bad)


def test_ensure_ffmpeg_available_raises_without_ffmpeg(no_binary):
    from services.transcription import ensure_ffmpeg_available

    no_binary("ffmpeg")
    with pytest.raises(capabilities.CapabilityUnavailableError):
        ensure_ffmpeg_available()


async def test_health_lists_missing_capabilities(client, no_git):
    r = await client.get("/health")
    body = r.json()
    # A missing optional binary is a degradation, not a liveness failure —
    # the Tauri shell polls this to decide whether to show the window.
    assert body["status"] == "ok"
    assert "git" in body["missing_capabilities"]
