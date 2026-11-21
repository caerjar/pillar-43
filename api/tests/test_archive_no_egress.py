"""Organization edition: intake and ask make no outbound network connection.

What "local" means here. Inside the container the model is not on loopback:
Ollama runs on the host and is reached at `host.docker.internal`
(docker-compose.archive.yml sets OLLAMA_URL). So the single allowed
destination, besides loopback (127.0.0.0/8, ::1), is the host named by the
configured `OLLAMA_URL`; its addresses are resolved before the guard goes up.
Every other `connect` (an API provider, a telemetry call, a model download)
is recorded and refused. The test asserts the record is empty, so a swallowed
exception inside the code under test cannot hide an attempt.

The Ollama stand-in is a real HTTP server on 127.0.0.1, so the real
`urllib` path through `call_ollama` is exercised, not a monkeypatched function.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest

import config
from services.archive import ask as ask_mod

TEXT = (
    "7. Reversion.\nThe Author may request reversion. "
    "The Publisher has nine months to reissue.\n"
)


def _allowed_addresses(ollama_url: str) -> set[str]:
    host = urlparse(ollama_url).hostname or ""
    out: set[str] = set()
    try:
        for info in socket.getaddrinfo(host, None):
            out.add(info[4][0])
    except OSError:
        pass  # host.docker.internal does not resolve outside Docker
    return out


def _is_local(addr: str, allowed: set[str]) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return ip.is_loopback or addr in allowed


@pytest.fixture
def egress_guard(monkeypatch):
    """Refuse and record every non-local connect. Yields the record."""
    allowed = _allowed_addresses(ask_mod.ollama_url())
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address) -> None:
        if isinstance(address, tuple) and not _is_local(str(address[0]), allowed):
            attempts.append(f"{address[0]}:{address[1]}")
            raise OSError(f"egress blocked: {address[0]}")

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield attempts


class _FakeOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps(
            {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": [
                                {
                                    "sentence": "Rights revert after nine months.",
                                    "cites": [1],
                                    "quote": {"passage": 1, "sentence": 2},
                                }
                            ],
                            "not_answered": False,
                            "would_answer": None,
                        }
                    )
                }
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def local_ollama(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    yield
    srv.shutdown()
    srv.server_close()


def _org_library(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    c = tmp_path / "library" / "contracts"
    c.mkdir()
    (c / "reversion.txt").write_text(TEXT)
    (tmp_path / "library" / "notes.txt").write_text("A note about rights reversion.\n")


def _index_by_hand() -> None:
    """One file + one chunk for the contract, so retrieval has something to
    return without running the embedder."""
    from services.db import get_db

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext, "
            "extracted_text, summary, topics, cataloged_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "library/contracts/reversion.txt",
                "library",
                "/x",
                "x",
                1,
                0,
                ".txt",
                TEXT,
                "s",
                "[]",
                0,
                0,
            ),
        )
        conn.execute(
            "INSERT INTO file_chunks (file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, 0, TEXT, 0, len(TEXT), None, "h"),
        )
        conn.commit()
    finally:
        conn.close()


def test_guard_blocks_and_records_a_remote_connect(egress_guard):
    with pytest.raises(OSError):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    assert egress_guard == ["93.184.216.34:80"]


def test_intake_and_ask_make_no_outbound_connection(
    tmp_path, monkeypatch, egress_guard, local_ollama
):
    _org_library(tmp_path, monkeypatch)
    from scripts import archive_cli
    from services import retrieval

    out = archive_cli.intake()
    assert out["counts"]["new"] == 2

    archive_cli.consent("library/contracts/reversion.txt", "model", "test")
    _index_by_hand()
    monkeypatch.setattr(retrieval, "_semantic_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        retrieval,
        "_ripgrep_hits",
        lambda *a, **k: [{"path": "library/contracts/reversion.txt", "score": 0.25}],
    )

    result = ask_mod.ask("When do rights revert?")

    assert result["answer"], "the stand-in model's answer reached the validator"
    assert egress_guard == [], f"outbound connection attempted: {egress_guard}"


def test_indexing_makes_no_outbound_connection(tmp_path, monkeypatch, egress_guard):
    """Indexing loads the embedding model. In the org edition that model must
    come from the image, never from Hugging Face at first use."""
    _org_library(tmp_path, monkeypatch)
    from services import embeddings
    from services.archive.index import index_library

    # A fresh process has no model in memory; a warm one would hide a download.
    embeddings.release_model()
    out = index_library()

    assert out["files_scanned"] >= 1
    assert out["errors"] == [], out["errors"]
    assert out["embedded"], "the embedder ran and stored vectors"
    assert egress_guard == [], f"outbound connection attempted: {egress_guard}"
