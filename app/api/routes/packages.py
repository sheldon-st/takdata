"""
Data package management (.zip upload/list/download/delete).

Routes:
  GET    /packages              — list all packages
  POST   /packages              — upload a .zip file
  GET    /packages/{package_id} — download a .zip file
  DELETE /packages/{package_id} — delete a package
"""

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import require_admin, require_viewer
from app.api.uploads import read_upload
from app.core.config import settings
from app.models.schemas import PackageInfo
from app.services.package_service import (
    delete_package,
    list_packages,
    package_download_name,
    package_path_for_id,
    save_package,
)

router = APIRouter(prefix="/packages", tags=["Packages"])

_MAX_PACKAGE_SIZE = 100 * 1024 * 1024  # 100 MB


@router.get("", response_model=list[PackageInfo])
async def get_packages(_: dict = Depends(require_viewer)):
    return list_packages(settings.packages_dir)


@router.post("", response_model=PackageInfo, status_code=201)
async def upload_package(
    file: UploadFile,
    _: dict = Depends(require_admin),
):
    data = await read_upload(file, suffix=".zip", max_bytes=_MAX_PACKAGE_SIZE)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(status_code=400, detail="File is not a valid zip archive")
    return save_package(settings.packages_dir, file.filename, data)


@router.get("/{package_id}")
async def download_package(package_id: str, _: dict = Depends(require_viewer)):
    path = package_path_for_id(settings.packages_dir, package_id)
    if not path:
        raise HTTPException(status_code=404, detail="Package not found")
    return FileResponse(
        path=path,
        media_type="application/zip",
        filename=package_download_name(settings.packages_dir, path),
    )


@router.delete("/{package_id}", status_code=204)
async def remove_package(package_id: str, _: dict = Depends(require_admin)):
    if not delete_package(settings.packages_dir, package_id):
        raise HTTPException(status_code=404, detail="Package not found")
