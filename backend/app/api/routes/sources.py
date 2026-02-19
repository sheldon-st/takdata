"""
Data source CRUD within an enablement.

Routes:
  GET    /enablements/{id}/sources          — list sources
  POST   /enablements/{id}/sources          — add source
  PUT    /enablements/{id}/sources/{sid}    — update source
  DELETE /enablements/{id}/sources/{sid}    — remove source
"""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_db, get_runtime
from app.core.runtime_manager import RuntimeManager
from app.models.schemas import SourceCreate, SourceResponse, SourceUpdate
from app.services.enablement_service import (
    build_enablement_config,
    create_source,
    delete_source,
    get_enablement,
    get_source,
    list_sources,
    update_source,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["Sources"])


@router.get("/enablements/{enablement_id}/sources", response_model=list[SourceResponse])
async def get_sources(
    enablement_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _require_enablement(db, enablement_id)
    return await list_sources(db, enablement_id)


@router.post(
    "/enablements/{enablement_id}/sources",
    response_model=SourceResponse,
    status_code=201,
)
async def add_source(
    enablement_id: int,
    body: SourceCreate,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    await _require_enablement(db, enablement_id)
    data = body.model_dump()
    source = await create_source(db, enablement_id, data)

    # Hot-reload enablement if it's running
    await _maybe_reload(db, runtime, enablement_id)
    return source


@router.put(
    "/enablements/{enablement_id}/sources/{source_id}",
    response_model=SourceResponse,
)
async def edit_source(
    enablement_id: int,
    source_id: int,
    body: SourceUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    await _require_source(db, enablement_id, source_id)
    updates = body.model_dump(exclude_none=True)
    source = await update_source(db, enablement_id, source_id, updates)

    await _maybe_reload(db, runtime, enablement_id)
    return source


@router.delete("/enablements/{enablement_id}/sources/{source_id}", status_code=204)
async def remove_source(
    enablement_id: int,
    source_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    await _require_source(db, enablement_id, source_id)
    await delete_source(db, enablement_id, source_id)
    await _maybe_reload(db, runtime, enablement_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_enablement(db: aiosqlite.Connection, enablement_id: int) -> dict:
    row = await get_enablement(db, enablement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enablement not found")
    return row


async def _require_source(
    db: aiosqlite.Connection, enablement_id: int, source_id: int
) -> dict:
    await _require_enablement(db, enablement_id)
    row = await get_source(db, enablement_id, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return row


async def _maybe_reload(
    db: aiosqlite.Connection, runtime: RuntimeManager, enablement_id: int
) -> None:
    """If the enablement is currently running, reload it with updated config."""
    if runtime.is_enablement_running(enablement_id):
        row = await get_enablement(db, enablement_id)
        if row:
            await runtime.restart_enablement(enablement_id, build_enablement_config(row))
