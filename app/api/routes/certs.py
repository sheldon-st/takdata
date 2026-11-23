"""
TLS certificate management (.p12 upload/list/delete).

Routes:
  POST   /tak/certs           — upload .p12 file
  GET    /tak/certs           — list stored certs
  DELETE /tak/certs/{cert_id} — delete a cert
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import require_admin, require_viewer
from app.api.uploads import read_upload
from app.core.config import settings
from app.models.schemas import CertInfo
from app.services.cert_service import delete_cert, list_certs, save_cert

router = APIRouter(prefix="/tak/certs", tags=["Certificates"])

_MAX_CERT_SIZE = 1 * 1024 * 1024  # 1 MB


@router.get("", response_model=list[CertInfo])
async def get_certs(_: dict = Depends(require_viewer)):
    return list_certs(settings.certs_dir)


@router.post("", response_model=CertInfo, status_code=201)
async def upload_cert(
    file: UploadFile,
    _: dict = Depends(require_admin),
):
    data = await read_upload(file, suffix=".p12", max_bytes=_MAX_CERT_SIZE)
    return save_cert(settings.certs_dir, file.filename, data)


@router.delete("/{cert_id}", status_code=204)
async def remove_cert(cert_id: str, _: dict = Depends(require_admin)):
    if not delete_cert(settings.certs_dir, cert_id):
        raise HTTPException(status_code=404, detail="Certificate not found")
