"""
Business logic for enablement + source CRUD and startup restore.
Bridges API routes ↔ SQLite ↔ RuntimeManager.
"""

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

from app.core.runtime_manager import RuntimeManager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TAK config helpers
# ---------------------------------------------------------------------------

async def get_tak_config(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute("SELECT * FROM tak_config WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else {}


async def update_tak_config(db: aiosqlite.Connection, data: dict) -> dict:
    fields = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values())
    await db.execute(
        f"UPDATE tak_config SET {fields}, updated_at = datetime('now') WHERE id = 1",
        values,
    )
    await db.commit()
    return await get_tak_config(db)


# ---------------------------------------------------------------------------
# Enablement CRUD
# ---------------------------------------------------------------------------

async def list_enablements(db: aiosqlite.Connection) -> list[dict]:
    rows = await (await db.execute("SELECT * FROM enablements ORDER BY id")).fetchall()
    result = []
    for row in rows:
        e = dict(row)
        e["sources"] = await _get_sources_for(db, e["id"])
        result.append(e)
    return result


async def get_enablement(db: aiosqlite.Connection, enablement_id: int) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM enablements WHERE id = ?", (enablement_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    e = dict(row)
    e["sources"] = await _get_sources_for(db, enablement_id)
    return e


async def create_enablement(db: aiosqlite.Connection, data: dict) -> dict:
    cursor = await db.execute(
        """INSERT INTO enablements
               (type_id, name, enabled, cot_stale, alt_upper, alt_lower, uid_key,
                geo_filter_min_lat, geo_filter_max_lat, geo_filter_min_lon, geo_filter_max_lon,
                feature_count, updates_per_second, features_per_update, selection_strategy)
           VALUES
               (:type_id, :name, :enabled, :cot_stale, :alt_upper, :alt_lower, :uid_key,
                :geo_filter_min_lat, :geo_filter_max_lat, :geo_filter_min_lon, :geo_filter_max_lon,
                :feature_count, :updates_per_second, :features_per_update, :selection_strategy)""",
        data,
    )
    await db.commit()
    return await get_enablement(db, cursor.lastrowid)


async def update_enablement(
    db: aiosqlite.Connection, enablement_id: int, data: dict
) -> Optional[dict]:
    if not data:
        return await get_enablement(db, enablement_id)
    fields = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values()) + [enablement_id]
    await db.execute(
        f"UPDATE enablements SET {fields}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()
    return await get_enablement(db, enablement_id)


async def delete_enablement(db: aiosqlite.Connection, enablement_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM enablements WHERE id = ?", (enablement_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Source CRUD
# ---------------------------------------------------------------------------

async def _get_sources_for(db: aiosqlite.Connection, enablement_id: int) -> list[dict]:
    rows = await (
        await db.execute(
            "SELECT * FROM sources WHERE enablement_id = ? ORDER BY id",
            (enablement_id,),
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def list_sources(db: aiosqlite.Connection, enablement_id: int) -> list[dict]:
    return await _get_sources_for(db, enablement_id)


async def get_source(
    db: aiosqlite.Connection, enablement_id: int, source_id: int
) -> Optional[dict]:
    cursor = await db.execute(
        "SELECT * FROM sources WHERE id = ? AND enablement_id = ?",
        (source_id, enablement_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def create_source(
    db: aiosqlite.Connection, enablement_id: int, data: dict
) -> dict:
    data["enablement_id"] = enablement_id
    cursor = await db.execute(
        """INSERT INTO sources
               (enablement_id, name, base_url, endpoint, sleep_interval,
                lat, lon, distance, enabled)
           VALUES
               (:enablement_id, :name, :base_url, :endpoint, :sleep_interval,
                :lat, :lon, :distance, :enabled)""",
        data,
    )
    await db.commit()
    return await get_source(db, enablement_id, cursor.lastrowid)


async def update_source(
    db: aiosqlite.Connection, enablement_id: int, source_id: int, data: dict
) -> Optional[dict]:
    if not data:
        return await get_source(db, enablement_id, source_id)
    fields = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values()) + [source_id, enablement_id]
    await db.execute(
        f"UPDATE sources SET {fields} WHERE id = ? AND enablement_id = ?",
        values,
    )
    await db.commit()
    return await get_source(db, enablement_id, source_id)


async def delete_source(
    db: aiosqlite.Connection, enablement_id: int, source_id: int
) -> bool:
    cursor = await db.execute(
        "DELETE FROM sources WHERE id = ? AND enablement_id = ?",
        (source_id, enablement_id),
    )
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Build runtime config from DB row
# ---------------------------------------------------------------------------

def build_enablement_config(enablement: dict) -> dict:
    """
    Merge the enablement row fields into a flat config dict that
    plugins and converters expect (uppercase keys for CoT fields).
    """
    cfg = {
        **enablement,
        "COT_STALE": str(enablement.get("cot_stale", 300)),
        "UID_KEY": enablement.get("uid_key", "ICAO"),
        "ALT_UPPER": str(enablement.get("alt_upper", 0)),
        "ALT_LOWER": str(enablement.get("alt_lower", 0)),
        "SLEEP_INTERVAL": str(
            min(
                (s.get("sleep_interval", 5) for s in enablement.get("sources", [])),
                default=5,
            )
        ),
        "sources": enablement.get("sources", []),
    }
    # Geo bounding-box filter — pass raw values (None disables the filter)
    cfg["geo_filter_min_lat"] = enablement.get("geo_filter_min_lat")
    cfg["geo_filter_max_lat"] = enablement.get("geo_filter_max_lat")
    cfg["geo_filter_min_lon"] = enablement.get("geo_filter_min_lon")
    cfg["geo_filter_max_lon"] = enablement.get("geo_filter_max_lon")
    # Synthetic harness workload model (None for non-synthetic types)
    cfg["feature_count"] = enablement.get("feature_count")
    cfg["updates_per_second"] = enablement.get("updates_per_second")
    cfg["features_per_update"] = enablement.get("features_per_update")
    cfg["selection_strategy"] = enablement.get("selection_strategy")
    return cfg


# ---------------------------------------------------------------------------
# Startup restore
# ---------------------------------------------------------------------------

async def restore_active_enablements(
    runtime: RuntimeManager, db_path: Path
) -> None:
    """
    Re-arm all enabled=1 enablements on API startup.
    Connects to TAK server first; logs errors but does not crash the API.
    """
    import aiosqlite as _aiosqlite

    async with _aiosqlite.connect(db_path) as db:
        db.row_factory = _aiosqlite.Row

        # Load and connect TAK config
        cursor = await db.execute("SELECT * FROM tak_config WHERE id = 1")
        row = await cursor.fetchone()
        if not row:
            log.info("No TAK config — skipping startup restore")
            return

        tak_cfg = dict(row)
        if not tak_cfg.get("cot_url"):
            log.info("TAK URL not set — skipping startup restore")
            return

        # Resolve cert reference to absolute path
        from app.core.config import settings as _settings
        from app.services.cert_service import resolve_cert_path as _resolve_cert_path

        cert_ref = tak_cfg.get("cert_path")
        if cert_ref:
            resolved = _resolve_cert_path(_settings.certs_dir, cert_ref)
            if resolved:
                tak_cfg["cert_path"] = resolved
            else:
                log.warning("Startup: cert not found for ref %r, connecting without cert", cert_ref)
                tak_cfg["cert_path"] = ""

        try:
            await runtime.connect_tak(tak_cfg)
        except Exception as exc:
            log.error("Startup: TAK connect failed: %s", exc)
            return

        # Restore enabled enablements
        rows = await (
            await db.execute("SELECT * FROM enablements WHERE enabled = 1")
        ).fetchall()

        for row in rows:
            enablement = dict(row)
            eid = enablement["id"]
            sources = await _get_sources_for(db, eid)
            enablement["sources"] = sources
            config = build_enablement_config(enablement)

            try:
                await runtime.start_enablement(eid, enablement["type_id"], config)
            except Exception as exc:
                log.error("Startup: failed to start enablement %d: %s", eid, exc)
