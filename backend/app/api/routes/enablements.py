"""
Enablement type catalog and per-enablement CRUD + start/stop.

Routes:
  GET    /enablement-types               — list registered plugin types
  GET    /enablements                    — list all configured enablements
  POST   /enablements                    — create new enablement
  GET    /enablements/{id}               — get one enablement
  PUT    /enablements/{id}               — update config
  DELETE /enablements/{id}               — delete
  POST   /enablements/{id}/start         — arm (start worker)
  POST   /enablements/{id}/stop          — disarm (stop worker)
  GET    /enablements/{id}/known-sources — pre-configured source templates (plugin-specific)
"""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_db, get_runtime
from app.core.runtime_manager import RuntimeManager
from app.enablements.registry import get_plugin_class, list_registered
from app.models.schemas import (
    EnablementCreate,
    EnablementResponse,
    EnablementTypeInfo,
    EnablementUpdate,
)
from app.services.enablement_service import (
    build_enablement_config,
    create_enablement,
    delete_enablement,
    get_enablement,
    list_enablements,
    update_enablement,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["Enablements"])


# ---------------------------------------------------------------------------
# Enablement type catalog
# ---------------------------------------------------------------------------

@router.get("/enablement-types", response_model=list[EnablementTypeInfo])
async def get_enablement_types():
    """List all registered enablement plugin types."""
    return list_registered()


# ---------------------------------------------------------------------------
# Enablement CRUD
# ---------------------------------------------------------------------------

@router.get("/enablements", response_model=list[EnablementResponse])
async def get_enablements(
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    rows = await list_enablements(db)
    return [_enrich(e, runtime) for e in rows]


@router.post("/enablements", response_model=EnablementResponse, status_code=201)
async def post_enablement(
    body: EnablementCreate,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    # Validate type_id is registered
    try:
        get_plugin_class(body.type_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = await create_enablement(db, body.model_dump())
    return _enrich(row, runtime)


@router.get("/enablements/{enablement_id}", response_model=EnablementResponse)
async def get_one_enablement(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")
    return _enrich(row, runtime)


@router.put("/enablements/{enablement_id}", response_model=EnablementResponse)
async def put_enablement(
    enablement_id: int,
    body: EnablementUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")

    updates = body.model_dump(exclude_none=True)
    updated = await update_enablement(db, enablement_id, updates)

    # Hot-reload if running
    if runtime.is_enablement_running(enablement_id):
        new_config = build_enablement_config(updated)
        await runtime.restart_enablement(enablement_id, new_config)

    return _enrich(updated, runtime)


@router.delete("/enablements/{enablement_id}", status_code=204)
async def del_enablement(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    await runtime.stop_enablement(enablement_id)
    deleted = await delete_enablement(db, enablement_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Enablement not found")


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

@router.post("/enablements/{enablement_id}/start")
async def start_enablement(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")

    if not runtime.is_connected:
        raise HTTPException(
            status_code=409,
            detail="TAK server not connected. POST /api/v1/tak/connect first.",
        )

    config = build_enablement_config(row)
    try:
        await runtime.start_enablement(enablement_id, row["type_id"], config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Mark as enabled in DB
    await update_enablement(db, enablement_id, {"enabled": 1})
    return {"status": "started", "id": enablement_id}


@router.post("/enablements/{enablement_id}/stop")
async def stop_enablement(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")

    await runtime.stop_enablement(enablement_id)
    await update_enablement(db, enablement_id, {"enabled": 0})
    return {"status": "stopped", "id": enablement_id}


# ---------------------------------------------------------------------------
# Plugin-specific known sources (for UI "add from template")
# ---------------------------------------------------------------------------

@router.get("/enablements/{enablement_id}/known-sources")
async def known_sources(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")

    try:
        plugin_cls = get_plugin_class(row["type_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    getter = getattr(plugin_cls, "get_known_sources", None)
    return getter() if callable(getter) else []


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _enrich(row: dict, runtime: RuntimeManager) -> dict:
    """Attach live 'running' flag to a DB row before returning."""
    return {**row, "running": runtime.is_enablement_running(row["id"])}
