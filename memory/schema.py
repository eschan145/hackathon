"""SQLite schema + tiny migration helper for the memory subsystem.

Plain ``sqlite3`` is used (no ORM) for hackathon speed/simplicity per
ARCHITECTURE.md section 8. All DDL lives here so `store.py` just calls
`init_db(conn)` once at startup.

Tables:
    preferences        -- generic key/value user preferences, namespaced by category
    contacts           -- contact book (name/email + free-form metadata)
    app_usage          -- frequency table for "most used app" queries
    tasks              -- persisted Task/TaskGraph/history (see core.models)
    credentials_ref     -- OPAQUE reference keys only, never secrets (see CredentialVault)
    shopping_preferences -- per-category shopping preferences (e.g. "soap" -> fragrance-free)
    browser_preferences -- misc browser-related key/value preferences
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    value TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (key, category)
);

CREATE TABLE IF NOT EXISTS contacts (
    name TEXT PRIMARY KEY,
    email TEXT,
    metadata_json TEXT,
    last_used_at REAL,
    use_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_usage (
    app_name TEXT PRIMARY KEY,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at REAL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    source TEXT,
    state TEXT,
    created_at REAL,
    completed_at REAL,
    graph_json TEXT,
    history_json TEXT,
    success INTEGER
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_task
ON conversation_messages(task_id, created_at);

CREATE TABLE IF NOT EXISTS credentials_ref (
    service TEXT PRIMARY KEY,
    ref_key TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS shopping_preferences (
    category TEXT PRIMARY KEY,
    preference_json TEXT
);

CREATE TABLE IF NOT EXISTS browser_preferences (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def default_db_path() -> Path:
    """Default DB location: <project_root>/data/memory.sqlite3."""
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "memory.sqlite3"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Idempotent schema creation + trivial version bookkeeping.

    Hackathon-scale "migration": since we only ever add tables/columns,
    just re-run the DDL (CREATE TABLE IF NOT EXISTS) and stamp the version
    row if missing. A real migration runner would diff SCHEMA_VERSION vs
    the stored version and apply incremental ALTERs.
    """
    with conn:
        conn.executescript(_DDL)
        row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] < SCHEMA_VERSION:
            conn.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
