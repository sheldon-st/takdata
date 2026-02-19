"""
TAK server configuration and connection management.

Routes:
  GET    /tak/config       — read current config
  PUT    /tak/config       — update config
  POST   /tak/connect      — connect / reconnect
  POST   /tak/disconnect   — disconnect
  GET    /tak/status       — live connection status
"""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_db, get_runtime
from app.core.runtime_manager import RuntimeManager
from app.models.schemas import TakConfigResponse, TakConfigUpdate, TakStatusResponse
from app.services.enablement_service import get_tak_config, update_tak_config

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tak", tags=["TAK Server"])


@router.get("/config", response_model=TakConfigResponse)
async def read_tak_config(db: aiosqlite.Connection = Depends(get_db)):
    return await get_tak_config(db)


@router.put("/config", response_model=TakConfigResponse)
async def write_tak_config(
    body: TakConfigUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    data = body.model_dump(exclude_none=False)
    # Don't store cert_password if None was explicitly passed
    if data.get("cert_password") is None:
        data.pop("cert_password", None)
    return await update_tak_config(db, data)


@router.post("/connect")
async def connect_tak(
    db: aiosqlite.Connection = Depends(get_db),
    runtime: RuntimeManager = Depends(get_runtime),
):
    """Connect (or reconnect) to the TAK server using the stored config."""
    tak_cfg = await get_tak_config(db)
    if not tak_cfg.get("cot_url"):
        raise HTTPException(status_code=400, detail="TAK server URL not configured")

    try:
        await runtime.connect_tak(tak_cfg)
        return {"status": "connected", "url": tak_cfg["cot_url"]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connection failed: {exc}") from exc


@router.post("/disconnect")
async def disconnect_tak(runtime: RuntimeManager = Depends(get_runtime)):
    await runtime.disconnect_tak()
    return {"status": "disconnected"}


@router.get("/status", response_model=TakStatusResponse)
async def tak_status(runtime: RuntimeManager = Depends(get_runtime)):
    status = runtime.get_status()
    return {
        "connected": status["tak_connected"],
        "url": status["tak_url"],
        "queue_size": status["tx_queue_size"],
    }
