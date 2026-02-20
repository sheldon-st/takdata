"""
Data package file management (.zip uploads/downloads).
Packages are stored as {uuid}_{original_name}.zip under data/packages/.
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def list_packages(packages_dir: Path) -> list[dict]:
    """Return all stored packages as [{package_id, filename, size}]."""
    if not packages_dir.exists():
        return []
    result = []
    for path in sorted(packages_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        package_id, _, original = path.stem.partition("_")
        result.append(
            {
                "package_id": package_id,
                "filename": original + ".zip" if original else path.name,
                "size": path.stat().st_size,
            }
        )
    return result


def package_path_for_id(packages_dir: Path, package_id: str) -> Optional[Path]:
    """Find the .zip file for a given package_id. Returns None if not found."""
    matches = list(packages_dir.glob(f"{package_id}_*.zip"))
    if not matches:
        exact = packages_dir / f"{package_id}.zip"
        if exact.exists():
            return exact
        return None
    return matches[0]


async def save_package(packages_dir: Path, filename: str, data: bytes) -> dict:
    """Persist an uploaded .zip file. Returns {package_id, filename, size}."""
    packages_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")
    package_id = str(uuid.uuid4()).replace("-", "")[:16]
    dest = packages_dir / f"{package_id}_{safe_name}.zip"

    dest.write_bytes(data)
    log.info("Saved package %s as %s", filename, dest)
    return {"package_id": package_id, "filename": filename, "size": len(data)}


def delete_package(packages_dir: Path, package_id: str) -> bool:
    """Delete a stored package. Returns True if deleted."""
    path = package_path_for_id(packages_dir, package_id)
    if path and path.exists():
        path.unlink()
        log.info("Deleted package %s", path)
        return True
    return False
