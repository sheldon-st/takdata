"""
TAK Manager API — FastAPI entrypoint.

Start with:
  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Or via Docker Compose (see docker-compose.yml).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import enablements package to populate the plugin registry
import app.enablements
from app import __version__
from app.api.deps import get_current_user
from app.api.routes import certs, enablements, packages, sources, status, tak_config
from app.core.config import settings
from app.core.runtime_manager import runtime_manager
from app.models.db import init_db
from app.services.enablement_service import restore_active_enablements

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --------------- Startup ---------------
    log.info("Initialising database at %s", settings.db_path)
    await init_db(settings.db_path)

    log.info("Restoring active enablements from DB")
    await restore_active_enablements(runtime_manager, settings.db_path)

    yield

    # --------------- Shutdown ---------------
    log.info("Shutting down — stopping all enablements and TAK connection")
    await runtime_manager.disconnect_tak()


app = FastAPI(
    title="TAK Manager API",
    description=(
        "Control plane for streaming live data into a TAK Server as Cursor-on-Target. "
        "Plugin-based enablements cover ADS-B aircraft, AIS vessels and a synthetic "
        "load-test harness."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — only needed when the UI is served from a different origin than /api.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
app.include_router(tak_config.router, prefix=PREFIX)
app.include_router(certs.router, prefix=PREFIX)
app.include_router(packages.router, prefix=PREFIX)
app.include_router(enablements.router, prefix=PREFIX)
app.include_router(sources.router, prefix=PREFIX)
app.include_router(status.router, prefix=PREFIX)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "TAK Manager API",
        "docs": "/docs",
        "status": "/api/v1/status",
    }


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness probe for container orchestration. Unauthenticated by design."""
    return {"status": "ok", "version": __version__}


@app.get(f"{PREFIX}/me", tags=["Auth"])
async def me(user: dict = Depends(get_current_user)):
    """Return the current authenticated user's identity and role."""
    role = "admin" if "tak-manager-admin" in user["groups"] else "viewer"
    return {
        "username": user["username"],
        "role": role,
        "auth_enabled": settings.auth_enabled,
    }
