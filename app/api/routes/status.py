"""
System status — HTTP snapshot + WebSocket live stream.

Routes:
  GET /status        — full snapshot
  WS  /ws/status     — push update every 2 seconds
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_runtime, require_viewer
from app.core.runtime_manager import RuntimeManager
from app.models.schemas import StatusResponse

log = logging.getLogger(__name__)
router = APIRouter(tags=["Status"])


@router.get("/status", response_model=StatusResponse)
async def get_status(
    runtime: RuntimeManager = Depends(get_runtime),
    _: dict = Depends(require_viewer),
):
    return runtime.get_status()


@router.websocket("/ws/status")
async def ws_status(
    websocket: WebSocket,
    runtime: RuntimeManager = Depends(get_runtime),
    _: dict = Depends(require_viewer),
):
    await websocket.accept()
    log.debug("WebSocket client connected: %s", websocket.client)
    try:
        while True:
            status = runtime.get_status()
            await websocket.send_json(status)
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        log.debug("WebSocket client disconnected: %s", websocket.client)
    except Exception as exc:
        log.warning("WebSocket error: %s", exc)
