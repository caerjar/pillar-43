"""The embed pass must survive a *transient* embeddings-service timeout.

Regression: a full-vault re-embed stalled at ~12% because one batch timed out
(embeddings service momentarily CPU-thrashed under load), the RuntimeError
propagated up, and the pass silently skipped every remaining passage. Per-batch
retry-with-backoff fixes it; a genuinely-down service still gives up so the
pass can resume next run (chunks stay embedded_at=NULL).
"""

from __future__ import annotations

import pytest

from services.catalog import embed as embed_mod


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Don't actually wait out the backoff in tests.
    monkeypatch.setattr(embed_mod.time, "sleep", lambda *_: None)


def test_retry_recovers_from_transient_timeout(monkeypatch):
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Embeddings service unreachable: timed out")
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(embed_mod, "embed_texts", flaky)

    out = embed_mod._embed_batch_with_retry(["a", "b"])
    assert out == [[0.1, 0.2], [0.1, 0.2]]
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_retry_gives_up_after_exhausting_attempts(monkeypatch):
    calls = {"n": 0}

    def always_down(texts):
        calls["n"] += 1
        raise RuntimeError("Embeddings service unreachable: timed out")

    monkeypatch.setattr(embed_mod, "embed_texts", always_down)

    with pytest.raises(RuntimeError):
        embed_mod._embed_batch_with_retry(["a"])
    assert calls["n"] == embed_mod._EMBED_RETRY_ATTEMPTS  # tried the full budget


def test_success_on_first_try_does_not_retry(monkeypatch):
    calls = {"n": 0}

    def ok(texts):
        calls["n"] += 1
        return [[1.0] for _ in texts]

    monkeypatch.setattr(embed_mod, "embed_texts", ok)

    assert embed_mod._embed_batch_with_retry(["x"]) == [[1.0]]
    assert calls["n"] == 1
