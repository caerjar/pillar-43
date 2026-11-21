"""In-process embeddings (fastembed), replacing the `embeddings` container.

Most of this file is contract, not behaviour: the public surface has survived
three implementations (fastembed → HTTP client → fastembed) precisely because
callers were never allowed to see the difference, and the caching/release
semantics are what keep a ~64MB model from being constructed on every API boot
or held forever after a catalog run.

The one test that touches the real model is marked `integration` — it downloads
weights on a cold cache, which is exactly the kind of thing `test-api-fast`
should skip. It earns its place by pinning **L2 normalisation**, which is not
cosmetic: the vector store treats cosine similarity as a plain dot product, so
if a future model or version returned un-normalised vectors, every similarity
score would be silently wrong rather than erroring.
"""

import pytest

from config import settings
from services import embeddings


@pytest.fixture(autouse=True)
def _clean_model_cache():
    embeddings.release_model()
    yield
    embeddings.release_model()


# ── the contract callers depend on ───────────────────────────────────────────


def test_dims_matches_the_active_model(monkeypatch):
    monkeypatch.setattr(
        settings, "effective_embedding_model", lambda: "BAAI/bge-base-en-v1.5"
    )
    assert embeddings.effective_dims() == 768


def test_dims_falls_back_for_an_unknown_model(monkeypatch):
    monkeypatch.setattr(settings, "effective_embedding_model", lambda: "who/knows")
    assert embeddings.effective_dims() == 384


def test_empty_batch_short_circuits(monkeypatch):
    """Must not construct the model just to embed nothing — the catalog calls
    this per batch and an empty tail batch is normal."""

    def boom(_name):
        raise AssertionError("model must not be loaded for an empty batch")

    monkeypatch.setattr(embeddings, "_get_model", boom)
    assert embeddings.embed_texts([]) == []


def test_unknown_model_is_rejected_by_name(monkeypatch):
    monkeypatch.setattr(settings, "effective_embedding_model", lambda: "nope/nope")
    with pytest.raises(ValueError, match="Unknown embedding model"):
        embeddings._resolve(None)


# ── load-once / release semantics ────────────────────────────────────────────


def test_model_is_constructed_once_and_reused(monkeypatch):
    builds = []

    class _Fake:
        def embed(self, texts):
            return ([0.0] * 384 for _ in texts)

    def fake_ctor(*_a, **kwargs):
        builds.append(kwargs.get("model_name"))
        return _Fake()

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", fake_ctor)

    embeddings.embed_texts(["one"])
    embeddings.embed_texts(["two"])
    embeddings.embed_query("three")

    assert len(builds) == 1


def test_release_drops_the_cache(monkeypatch):
    class _Fake:
        def embed(self, texts):
            return ([0.0] * 384 for _ in texts)

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", lambda *a, **k: _Fake())

    embeddings.embed_texts(["x"])
    assert embeddings._models
    embeddings.release_model()
    assert not embeddings._models


def test_release_is_safe_when_nothing_is_loaded():
    embeddings.release_model()  # must not raise
    embeddings.release_model("BAAI/bge-small-en-v1.5")


def test_cache_dir_prefers_the_explicit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "bundled"))
    assert embeddings._cache_dir() == str(tmp_path / "bundled")


def test_cache_dir_falls_back_to_the_baked_model_dir(monkeypatch):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    assert embeddings._cache_dir() == embeddings.BAKED_MODEL_DIR


# ── the real model ───────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
def test_real_model_returns_normalised_vectors_of_the_right_width():
    """The property Phase 1a's vector store is built on.

    Cosine reduces to a dot product only because these come back L2-normalised.
    Silently losing that would not raise anywhere — it would just make every
    similarity score wrong.
    """
    vectors = embeddings.embed_texts(["the archive is not a neutral container"])
    assert len(vectors) == 1
    v = vectors[0]
    assert len(v) == embeddings.effective_dims() == 384
    norm = sum(x * x for x in v) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-4)


@pytest.mark.integration
@pytest.mark.slow
def test_real_model_is_semantically_ordered():
    """A smoke test with teeth: related text must score above unrelated text,
    or the pipeline is wired up but useless."""
    a, b, c = embeddings.embed_texts(
        [
            "colonial archives and the silences they preserve",
            "archival silence under colonial administration",
            "a recipe for sourdough bread",
        ]
    )

    def dot(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert dot(a, b) > dot(a, c)
