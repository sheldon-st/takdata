"""
Data package management (.zip upload/list/download/delete).

Routes:
  GET    /packages              — list all packages
  POST   /packages              — upload a .zip file
  GET    /packages/{package_id} — download a .zip file
  DELETE /packages/{package_id} — delete a package
"""

import logging

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.package_service import (
    delete_package,
    list_packages,
    package_path_for_id,
    save_package,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/packages", tags=["Packages"])

_MAX_PACKAGE_SIZE = 100 * 1024 * 1024  # 100 MB


@router.get("", response_model=list[dict])
async def get_packages():
    return list_packages(settings.packages_dir)


@router.post("", response_model=dict, status_code=201)
async def upload_package(file: UploadFile):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    data = await file.read()
    if len(data) > _MAX_PACKAGE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    return await save_package(settings.packages_dir, file.filename, data)


@router.get("/{package_id}")
async def download_package(package_id: str):
    path = package_path_for_id(settings.packages_dir, package_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Package not found")

    # Recover original filename from the stored name
    _, _, original = path.stem.partition("_")
    download_name = original + ".zip" if original else path.name

    return FileResponse(
        path=path,
        media_type="application/zip",
        filename=download_name,
    )


@router.delete("/{package_id}", status_code=204)
async def remove_package(package_id: str):
    if not delete_package(settings.packages_dir, package_id):
        raise HTTPException(status_code=404, detail="Package not found")
