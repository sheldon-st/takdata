"""
Certificate file management (.p12 uploads).
Certs are stored as {uuid}.p12 under data/certs/.
The original filename is embedded in the stored name as {uuid}_{original}.p12
so it can be recovered for display.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def list_certs(certs_dir: Path) -> list[dict]:
    """Return all stored certs as [{cert_id, filename}]."""
    if not certs_dir.exists():
        return []
    result = []
    for path in sorted(certs_dir.glob("*.p12")):
        cert_id, _, original = path.stem.partition("_")
        result.append(
            {
                "cert_id": cert_id,
                "filename": original + ".p12" if original else path.name,
            }
        )
    return result


def cert_path_for_id(certs_dir: Path, cert_id: str) -> Optional[Path]:
    """Find the .p12 file for a given cert_id. Returns None if not found."""
    matches = list(certs_dir.glob(f"{cert_id}_*.p12"))
    if not matches:
        # Fallback: exact match (legacy cert files without original name)
        exact = certs_dir / f"{cert_id}.p12"
        if exact.exists():
            return exact
        return None
    return matches[0]


async def save_cert(certs_dir: Path, filename: str, data: bytes) -> dict:
    """Persist an uploaded .p12 file. Returns {cert_id, filename}."""
    certs_dir.mkdir(parents=True, exist_ok=True)

    # Sanitise original filename
    safe_name = Path(filename).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")
    cert_id = str(uuid.uuid4()).replace("-", "")[:16]
    dest = certs_dir / f"{cert_id}_{safe_name}.p12"

    dest.write_bytes(data)
    log.info("Saved cert %s as %s", filename, dest)
    return {"cert_id": cert_id, "filename": filename}


def delete_cert(certs_dir: Path, cert_id: str) -> bool:
    """Delete a stored cert. Returns True if deleted."""
    path = cert_path_for_id(certs_dir, cert_id)
    if path and path.exists():
        path.unlink()
        log.info("Deleted cert %s", path)
        return True
    return False


def resolve_cert_path(certs_dir: Path, cert_path_or_id: str) -> Optional[str]:
    """
    Resolve a cert reference (cert_id or relative path) to an absolute path
    suitable for passing to pytak.
    Returns None if not found.
    """
    if not cert_path_or_id:
        return None

    # Try as cert_id first
    p = cert_path_for_id(certs_dir, cert_path_or_id)
    if p:
        return str(p.resolve())

    # Try as a direct path
    direct = Path(cert_path_or_id)
    if direct.exists():
        return str(direct.resolve())

    return None
