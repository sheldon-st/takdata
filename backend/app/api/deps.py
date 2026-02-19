"""FastAPI dependency functions."""

from typing import AsyncGenerator

import aiosqlite

from app.core.config import settings
from app.core.runtime_manager import runtime_manager as _runtime
from app.models.db import get_db as _get_db


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield an aiosqlite connection using the configured DB path."""
    async for conn in _get_db(settings.db_path):
        yield conn


def get_runtime():
    """Return the module-level RuntimeManager singleton."""
    return _runtime
