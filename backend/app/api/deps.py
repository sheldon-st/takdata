"""FastAPI dependency functions."""

from typing import AsyncGenerator

import aiosqlite
from fastapi import Depends, HTTPException
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.core.runtime_manager import runtime_manager as _runtime
from app.models.db import get_db as _get_db

_ADMIN_GROUP = "tak-manager-admin"
_VIEWER_GROUP = "tak-manager-viewer"


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield an aiosqlite connection using the configured DB path."""
    async for conn in _get_db(settings.db_path):
        yield conn


def get_runtime():
    """Return the module-level RuntimeManager singleton."""
    return _runtime


def get_current_user(conn: HTTPConnection) -> dict:
    """Extract user identity from Authentik-injected request headers."""
    username = conn.headers.get("x-authentik-username")
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    groups_raw = conn.headers.get("x-authentik-groups", "")
    groups = [g.strip() for g in groups_raw.split("|") if g.strip()]
    return {"username": username, "groups": groups}


def require_viewer(user: dict = Depends(get_current_user)) -> dict:
    """Allow admins and viewers; reject everyone else."""
    if _ADMIN_GROUP not in user["groups"] and _VIEWER_GROUP not in user["groups"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Allow admins only."""
    if _ADMIN_GROUP not in user["groups"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
