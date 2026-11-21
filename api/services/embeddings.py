"""Embeddings — fastembed, in this process.

Public surface (unchanged across three implementations now, which is the point):
  - embed_texts(texts) -> list[list[float]]
  - embed_query(text)  -> list[float]
  - effective_dims()   -> int
  - release_model(model_name=None) -> None
  - MODEL_DIMS         -> dict[str, int]

This module has gone in a circle deliberately. It was fastembed in-process,
became an HTTP client to a dedicated `embeddings` container, and is fastembed
in-process again as of 2026-08-18 — because the desktop build cannot ship a
second container, and a loopback HTTP hop to a service in the same address
space buys nothing. The facade never changed, so every caller and the
retry/backoff wrapper in `catalog/embed.py` are untouched by all of it.

**Loading is lazy and cached, and that matters.** The model is ~64MB on disk
and costs a second or two plus a few hundred MB of RAM to construct. Building
it at import would make every API boot — including a boot that never embeds
anything — pay for it. `release_model()` exists so a long catalog run can hand
the memory back when it finishes.

Model files live wherever `FASTEMBED_CACHE_PATH` points, falling back to the
directory the image bakes the default model into. Nothing is ever downloaded
at run time: the desktop bundle ships the default model inside the app and
points this at it, so a first run works offline.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

# Dimensions per supported model. This used to be duplicated in
# `embeddings/main.py` under a "must stay in sync" comment; that file is gone
# and this is now the only copy. `routes/settings.py` reads it to populate the
# model dropdown.
MODEL_DIMS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "BAAI/bge-small-zh-v1.5": 512,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "Alibaba-NLP/gte-base-en-v1.5": 768,
    "Alibaba-NLP/gte-large-en-v1.5": 1024,
    "Qdrant/clip-ViT-B-32-text": 512,
    "jinaai/jina-embeddings-v2-base-en": 768,
    "jinaai/jina-embeddings-v2-small-en": 512,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "mixedbread-ai/mxbai-embed-large-v1": 1024,
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct": 1536,
    "Alibaba-NLP/gte-small-en-v1.5": 384,
    "intfloat/multilingual-e5-large": 1024,
    "intfloat/e5-small-v2": 384,
    "intfloat/e5-base-v2": 768,
}

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
_DEFAULT_DIMS = 384

_models: dict[str, Any] = {}
_models_lock = threading.Lock()


def _active_model_name() -> str:
    try:
        from config import settings

        return settings.effective_embedding_model()
    except Exception:
        return _DEFAULT_MODEL


def effective_dims() -> int:
    return MODEL_DIMS.get(_active_model_name(), _DEFAULT_DIMS)


# Where the api image bakes the default model at build time (api/Dockerfile).
BAKED_MODEL_DIR = os.getenv("PILLAR43_BAKED_MODEL_DIR", "/opt/fastembed")


def _cache_dir() -> str:
    """Where fastembed keeps model files. The archive never fetches a model:
    it loads the one baked into the image (or bundled by the desktop shell via
    `FASTEMBED_CACHE_PATH`) and fails loudly if the configured model is not
    there."""
    return os.getenv("FASTEMBED_CACHE_PATH", "").strip() or BAKED_MODEL_DIR


def _get_model(name: str) -> Any:
    """Load-and-cache. Held under a lock because the catalog embeds from a
    worker thread pool and two concurrent first-calls would otherwise each
    construct their own copy of a multi-hundred-MB model."""
    with _models_lock:
        if name not in _models:
            from fastembed import TextEmbedding

            log.info("Loading embedding model %s …", name)
            _models[name] = TextEmbedding(
                model_name=name,
                cache_dir=_cache_dir(),
                show_progress_bar=False,
                local_files_only=True,
            )
            log.info("Model %s loaded", name)
        return _models[name]


def _resolve(model: str | None) -> str:
    name = model or _active_model_name()
    if name not in MODEL_DIMS:
        raise ValueError(
            f"Unknown embedding model {name!r}. Supported: {sorted(MODEL_DIMS)}"
        )
    return name


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return float32 embedding vectors for a batch of texts.

    Vectors come back L2-normalised, which is what lets the vector store treat
    cosine similarity as a plain dot product.
    """
    if not texts:
        return []
    model = _get_model(_resolve(None))
    return [[float(x) for x in v] for v in model.embed(texts)]


def embed_query(text: str) -> list[float]:
    """Return a single embedding vector for a query string."""
    vectors = embed_texts([text])
    if not vectors:
        raise RuntimeError("embedding produced no vector for the query")
    return vectors[0]


def release_model(model_name: str | None = None) -> None:
    """Drop cached model(s) to hand back memory. Best-effort, never raises.

    Called after a catalog run. With no argument it releases everything; the
    next embed call reloads lazily.
    """
    with _models_lock:
        if model_name:
            released = _models.pop(model_name, None) is not None
        else:
            released = bool(_models)
            _models.clear()
    if released:
        log.info("Released embedding model(s): %s", model_name or "all")
