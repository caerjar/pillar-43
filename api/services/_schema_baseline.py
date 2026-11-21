"""Single source of truth for the baseline catalog schema.

Both `migrations/versions/0001_baseline.py` (Alembic) and `services/db.py`
(the in-memory DB fallback used by tests) import `BASELINE_SQL` from here.

When you change the schema, do NOT edit this constant — write a new
Alembic migration. This file is frozen.
"""

# Frozen baseline as of sprint 12. Any subsequent schema change must be its
# own Alembic migration; do not edit this string.
BASELINE_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path             TEXT    NOT NULL UNIQUE,
    mount                TEXT    NOT NULL,
    abs_path             TEXT    NOT NULL,
    sha256               TEXT    NOT NULL,
    size_bytes           INTEGER NOT NULL,
    mtime                REAL    NOT NULL,
    ext                  TEXT    NOT NULL,
    extracted_text       TEXT,
    summary              TEXT,
    topics               TEXT,
    entities             TEXT,
    cataloged_at         REAL,
    inbox_suggested_path TEXT,
    created_at           REAL    NOT NULL DEFAULT (unixepoch('now')),
    authorship           TEXT,
    qdrant_synced_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_files_sha256        ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_mount         ON files(mount);
CREATE INDEX IF NOT EXISTS idx_files_mtime         ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_files_ext           ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_rel_path      ON files(rel_path);
CREATE INDEX IF NOT EXISTS idx_files_size          ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_files_cataloged_at  ON files(cataloged_at);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
    USING fts5(extracted_text, content=files, content_rowid=id);

CREATE TRIGGER IF NOT EXISTS files_fts_insert
    AFTER INSERT ON files BEGIN
        INSERT INTO files_fts(rowid, extracted_text)
        VALUES (new.id, new.extracted_text);
    END;

CREATE TRIGGER IF NOT EXISTS files_fts_update
    AFTER UPDATE OF extracted_text ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, extracted_text)
        VALUES ('delete', old.id, old.extracted_text);
        INSERT INTO files_fts(rowid, extracted_text)
        VALUES (new.id, new.extracted_text);
    END;

CREATE TRIGGER IF NOT EXISTS files_fts_delete
    AFTER DELETE ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, extracted_text)
        VALUES ('delete', old.id, old.extracted_text);
    END;

CREATE TABLE IF NOT EXISTS file_connections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_a_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    file_b_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    score         REAL    NOT NULL,
    kind          TEXT    NOT NULL,
    shared_topics TEXT,
    discovered_at REAL    NOT NULL DEFAULT (unixepoch('now')),
    UNIQUE(file_a_id, file_b_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_connections_file_a ON file_connections(file_a_id);
CREATE INDEX IF NOT EXISTS idx_connections_file_b ON file_connections(file_b_id);
CREATE INDEX IF NOT EXISTS idx_connections_kind   ON file_connections(kind);
CREATE INDEX IF NOT EXISTS idx_connections_pair   ON file_connections(file_a_id, file_b_id);

CREATE TABLE IF NOT EXISTS threads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    label           TEXT,
    status          TEXT    NOT NULL,
    file_count      INTEGER NOT NULL,
    last_active     REAL    NOT NULL,
    files_json      TEXT    NOT NULL,
    path            TEXT,
    updated_at      REAL,
    generated_at    REAL    NOT NULL DEFAULT (unixepoch('now')),
    source          TEXT    NOT NULL DEFAULT 'ai',
    priority        TEXT    NOT NULL DEFAULT 'normal',
    status_override TEXT
);

CREATE INDEX IF NOT EXISTS idx_threads_status      ON threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_last_active ON threads(last_active);
CREATE INDEX IF NOT EXISTS idx_threads_source      ON threads(source);

CREATE TABLE IF NOT EXISTS topic_aliases (
    alias     TEXT NOT NULL,
    canonical TEXT NOT NULL,
    PRIMARY KEY (alias)
);

CREATE INDEX IF NOT EXISTS idx_topic_aliases_canonical ON topic_aliases(canonical);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT    NOT NULL,
    line         INTEGER NOT NULL,
    text         TEXT    NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    priority     TEXT,
    category     TEXT,
    due_date     TEXT,
    source       TEXT    NOT NULL DEFAULT 'checkbox',
    created_at   REAL    NOT NULL DEFAULT (unixepoch('now')),
    completed_at REAL,
    recurrence   TEXT,
    UNIQUE(path, line)
);

CREATE INDEX IF NOT EXISTS idx_tasks_path         ON tasks(path);
CREATE INDEX IF NOT EXISTS idx_tasks_done         ON tasks(done);
CREATE INDEX IF NOT EXISTS idx_tasks_priority     ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date     ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_completed_at ON tasks(completed_at);

CREATE TABLE IF NOT EXISTS file_checkpoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT    NOT NULL,
    sha          TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    saved_at     REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_path ON file_checkpoints(path, saved_at DESC);

CREATE TABLE IF NOT EXISTS ca_opacity (
    file_path        TEXT PRIMARY KEY,
    base_opacity     TEXT NOT NULL DEFAULT 'none',
    computed_opacity TEXT NOT NULL DEFAULT 'none',
    contagion_source TEXT,
    reason           TEXT,
    updated_at       REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE INDEX IF NOT EXISTS idx_ca_opacity_computed ON ca_opacity(computed_opacity);
"""
