"""
SQLite database schema and async helpers via aiosqlite.

Tables:
  tak_config   — single-row TAK server configuration
  enablements  — one row per user-configured enablement instance
  sources      — data sources per enablement
"""

import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

log = logging.getLogger(__name__)

# Resolved at import time; can be overridden via env (see app/core/config.py)
DB_PATH = Path("data/config.db")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tak_config (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    cot_url             TEXT    NOT NULL DEFAULT 'tls://localhost:8089',
    cert_path           TEXT,
    cert_password       TEXT,
    cot_host_id         TEXT    NOT NULL DEFAULT 'tak-manager',
    dont_check_hostname INTEGER NOT NULL DEFAULT 1,
    dont_verify         INTEGER NOT NULL DEFAULT 1,
    max_out_queue       INTEGER NOT NULL DEFAULT 1000,
    max_in_queue        INTEGER NOT NULL DEFAULT 1000,
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enablements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id             TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    enabled             INTEGER NOT NULL DEFAULT 1,
    cot_stale           INTEGER NOT NULL DEFAULT 300,
    alt_upper           INTEGER NOT NULL DEFAULT 0,
    alt_lower           INTEGER NOT NULL DEFAULT 0,
    uid_key             TEXT    NOT NULL DEFAULT 'ICAO',
    geo_filter_min_lat  REAL,
    geo_filter_max_lat  REAL,
    geo_filter_min_lon  REAL,
    geo_filter_max_lon  REAL,
    feature_count       INTEGER,
    updates_per_second  REAL,
    features_per_update INTEGER,
    selection_strategy  TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    enablement_id   INTEGER NOT NULL REFERENCES enablements(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    base_url        TEXT    NOT NULL,
    endpoint        TEXT    NOT NULL DEFAULT 'geo',
    sleep_interval  REAL    NOT NULL DEFAULT 5.0,
    lat             REAL,
    lon             REAL,
    distance        REAL             DEFAULT 25.0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


_GEO_FILTER_MIGRATIONS = [
    "ALTER TABLE enablements ADD COLUMN geo_filter_min_lat REAL",
    "ALTER TABLE enablements ADD COLUMN geo_filter_max_lat REAL",
    "ALTER TABLE enablements ADD COLUMN geo_filter_min_lon REAL",
    "ALTER TABLE enablements ADD COLUMN geo_filter_max_lon REAL",
    # Synthetic harness v2 — replace entity_count/target_rate_hz with explicit workload model
    "ALTER TABLE enablements ADD COLUMN feature_count INTEGER",
    "ALTER TABLE enablements ADD COLUMN updates_per_second REAL",
    "ALTER TABLE enablements ADD COLUMN features_per_update INTEGER",
    "ALTER TABLE enablements ADD COLUMN selection_strategy TEXT",
    # Wipe stale synthetic rows from v1 schema (user-confirmed)
    "DELETE FROM enablements WHERE type_id = 'synthetic' AND feature_count IS NULL",
    # Drop deprecated v1 cols (SQLite 3.35+)
    "ALTER TABLE enablements DROP COLUMN entity_count",
    "ALTER TABLE enablements DROP COLUMN target_rate_hz",
]


async def init_db(db_path: Optional[Path] = None) -> None:
    """Create tables and seed default TAK config row. Called from app lifespan."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.execute("INSERT OR IGNORE INTO tak_config (id) VALUES (1)")
        # Migrate existing databases that predate the geo-filter columns.
        for stmt in _GEO_FILTER_MIGRATIONS:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # Column already exists — safe to ignore
        await db.commit()
    log.info("Database initialised at %s", path)


async def get_db(db_path: Optional[Path] = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    FastAPI dependency that yields an aiosqlite connection.

    Usage:
        @router.get("/foo")
        async def handler(db: aiosqlite.Connection = Depends(get_db)):
            ...
    """
    path = db_path or DB_PATH
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
