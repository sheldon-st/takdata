"""
Data package file management (.zip uploads/downloads).

Packages live under data/packages/ as {package_id}_{original}.zip; see FileStore.
"""

from pathlib import Path

from app.services.file_store import FileStore


def _store(packages_dir: Path) -> FileStore:
    return FileStore(packages_dir, ".zip")


def list_packages(packages_dir: Path) -> list[dict]:
    """Return all stored packages as [{package_id, filename, size}], newest first."""
    return [
        {"package_id": e["id"], "filename": e["filename"], "size": e["size"]}
        for e in _store(packages_dir).list()
    ]


def package_path_for_id(packages_dir: Path, package_id: str) -> Path | None:
    return _store(packages_dir).path_for(package_id)


def package_download_name(packages_dir: Path, path: Path) -> str:
    return _store(packages_dir).display_name(path)


def save_package(packages_dir: Path, filename: str, data: bytes) -> dict:
    """Persist an uploaded .zip file. Returns {package_id, filename, size}."""
    saved = _store(packages_dir).save(filename, data)
    return {"package_id": saved["id"], "filename": saved["filename"], "size": saved["size"]}


def delete_package(packages_dir: Path, package_id: str) -> bool:
    return _store(packages_dir).delete(package_id)
