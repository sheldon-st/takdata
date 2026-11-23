"""
Certificate file management (.p12 uploads).

Certs live under data/certs/ as {cert_id}_{original}.p12; see FileStore.
"""

from pathlib import Path
from typing import Optional

from app.services.file_store import FileStore


def _store(certs_dir: Path) -> FileStore:
    return FileStore(certs_dir, ".p12")


def list_certs(certs_dir: Path) -> list[dict]:
    """Return all stored certs as [{cert_id, filename}], sorted by filename."""
    certs = [{"cert_id": e["id"], "filename": e["filename"]} for e in _store(certs_dir).list()]
    return sorted(certs, key=lambda c: c["filename"].lower())


def cert_path_for_id(certs_dir: Path, cert_id: str) -> Optional[Path]:
    return _store(certs_dir).path_for(cert_id)


def save_cert(certs_dir: Path, filename: str, data: bytes) -> dict:
    """Persist an uploaded .p12 file. Returns {cert_id, filename}."""
    saved = _store(certs_dir).save(filename, data)
    return {"cert_id": saved["id"], "filename": saved["filename"]}


def delete_cert(certs_dir: Path, cert_id: str) -> bool:
    return _store(certs_dir).delete(cert_id)


def resolve_cert_path(certs_dir: Path, cert_path_or_id: str) -> Optional[str]:
    """
    Resolve a stored cert reference to an absolute path suitable for pytak.

    Accepts a cert_id ("50576b7f4af14caa"), a path whose stem is a cert_id
    ("data/certs/50576b7f4af14caa"), or an existing absolute/relative path.
    Returns None if nothing matches.
    """
    if not cert_path_or_id:
        return None

    for candidate in (cert_path_or_id, Path(cert_path_or_id).stem.partition("_")[0]):
        path = cert_path_for_id(certs_dir, candidate)
        if path:
            return str(path.resolve())

    direct = Path(cert_path_or_id)
    if direct.is_file():
        return str(direct.resolve())
    return None
