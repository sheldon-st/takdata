"""
TLS certificate management (.p12 upload/list/delete).

Routes:
  POST   /tak/certs           — upload .p12 file
  GET    /tak/certs           — list stored certs
  DELETE /tak/certs/{cert_id} — delete a cert
"""

import logging

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.config import settings
from app.models.schemas import CertInfo
from app.services.cert_service import delete_cert, list_certs, save_cert

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tak/certs", tags=["Certificates"])

_MAX_CERT_SIZE = 1 * 1024 * 1024  # 1 MB


@router.get("", response_model=list[CertInfo])
async def get_certs():
    return list_certs(settings.certs_dir)


@router.post("", response_model=CertInfo, status_code=201)
async def upload_cert(file: UploadFile):
    if not file.filename or not file.filename.endswith(".p12"):
        raise HTTPException(status_code=400, detail="Only .p12 files are accepted")

    data = await file.read()
    if len(data) > _MAX_CERT_SIZE:
        raise HTTPException(status_code=413, detail="Certificate file too large (max 1 MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    return await save_cert(settings.certs_dir, file.filename, data)


@router.delete("/{cert_id}", status_code=204)
async def remove_cert(cert_id: str):
    if not delete_cert(settings.certs_dir, cert_id):
        raise HTTPException(status_code=404, detail="Certificate not found")
