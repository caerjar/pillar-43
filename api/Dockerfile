FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    git \
    gcc \
    python3-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the default embedding model into the image. The organization edition
# loads it from here with local_files_only, so indexing needs no network and
# never downloads at first use (services/embeddings.py).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')" \
    && chmod -R a+rX /opt/fastembed

COPY . .

RUN mkdir -p /tmp/.pillar43_no_extra

RUN addgroup --system app && adduser --system --ingroup app app
# Pre-create /data with `app` ownership so when docker-compose mounts the
# `pillar43_data` named volume here for the first time, the volume inherits
# this ownership (Docker copies the image's dir state into the empty volume
# at first attach). Without this, the volume is root-owned and the api
# process — running as `app` — gets `sqlite3.OperationalError: unable to
# open database file` on every startup.
RUN mkdir -p /data && chown app:app /data
ENV HOME=/tmp
# Unbuffered stdout/stderr so exception tracebacks reach `docker logs` immediately
# instead of sitting in Python's line buffer until the process exits.
ENV PYTHONUNBUFFERED=1

# Build stamp — surfaced via GET /health. Set via `docker compose build` args.
# Version comes from the git tag at release time (see .github/workflows/
# release.yml). "dev" for any build that isn't a tagged release — which is
# honest: an untagged build is not a release.
ARG PILLAR43_VERSION=dev
ENV PILLAR43_VERSION=${PILLAR43_VERSION}
ARG PILLAR43_API_SHA=unknown
ARG PILLAR43_WEB_SHA=unknown
ARG PILLAR43_BUILT_AT=unknown
ENV PILLAR43_API_SHA=${PILLAR43_API_SHA}
ENV PILLAR43_WEB_SHA=${PILLAR43_WEB_SHA}
ENV PILLAR43_BUILT_AT=${PILLAR43_BUILT_AT}

USER app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--access-log"]


# ── dev target ───────────────────────────────────────────────────────────────
# Adds the test + lint toolchain on top of the runtime image. Built by
# docker-compose.test.yml (`target: dev`) so pytest/ruff/mypy exist where the
# suite runs, without shipping them to production.
#
# Note: docker-compose.test.yml bind-mounts ./api over /app, so the *source*
# (including tests/) comes from the host at runtime — .dockerignore excluding
# tests/ from the image does not affect the test container.
FROM runtime AS dev

USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
USER app
