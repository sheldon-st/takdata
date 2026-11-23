"""Shared validation for multipart file uploads."""

from fastapi import HTTPException, UploadFile


async def read_upload(file: UploadFile, *, suffix: str, max_bytes: int) -> bytes:
    """Validate extension and size, reading at most max_bytes + 1 into memory."""
    if not file.filename or not file.filename.lower().endswith(suffix):
        raise HTTPException(status_code=400, detail=f"Only {suffix} files are accepted")

    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large (max {limit_mb} MB)")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return data
