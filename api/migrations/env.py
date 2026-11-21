"""Alembic env.py — runs migrations against the catalog SQLite database.

The DB path comes from `config.settings.db_path` so test fixtures that
monkeypatch `generated_path` work correctly. Override with the env var
``ALEMBIC_DB_URL`` to migrate a specific file (used by alembic CLI).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the `api/` package importable so we can read `config.settings`
_api_dir = Path(__file__).resolve().parent.parent
if str(_api_dir) not in sys.path:
    sys.path.insert(0, str(_api_dir))

config = context.config

# `configure_logging` is set to False by services.db._alembic_config, i.e. by
# every in-process `alembic upgrade` the api and worker run at startup. Those
# must not touch logging at all: fileConfig applies alembic.ini's
# `[logger_root] level = WARN` to the ROOT logger, which silences every app
# INFO line in the host process from the first migration onward — the api
# carried a _reconfigure_logging() workaround for this, and the worker, which
# had none, went dark ~30s after boot and made a mute Commons bot
# undiagnosable. The alembic CLI leaves the attribute unset and still gets the
# ini's logging config, which is the only context where it's wanted.
if config.config_file_name is not None and config.attributes.get(
    "configure_logging", True
):
    # disable_existing_loggers=False is critical: without it, every logger
    # created before Alembic runs (e.g. main.py's `logger = getLogger(__name__)`,
    # uvicorn.error, uvicorn.access) is disabled — silently swallowing every
    # subsequent log call including unhandled-exception tracebacks.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _resolve_db_url() -> str:
    """Choose the SQLite URL — only used when nothing was set programmatically.

    Resolution order:
      1. URL already on the Config (set by services.db.init_schema)
      2. ALEMBIC_DB_URL env var (CLI override)
      3. settings.db_path
      4. Throwaway path for offline tooling
    """
    existing = config.get_main_option("sqlalchemy.url")
    if existing:
        return existing
    override = os.getenv("ALEMBIC_DB_URL")
    if override:
        return override
    try:
        from config import settings

        return f"sqlite:///{settings.db_path}"
    except Exception:
        return "sqlite:///./alembic-throwaway.db"


# Resolve the URL only if it isn't already set on the Config object
# (init_schema sets it programmatically before invoking command.upgrade).
config.set_main_option("sqlalchemy.url", _resolve_db_url())

# Schema introspection isn't used (we hand-write migrations), so target_metadata
# stays None.
target_metadata = None


def run_migrations_offline() -> None:
    """Generate SQL from migrations without a live connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live SQLite connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite "batch" mode is the safe way to do ALTER TABLE
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
