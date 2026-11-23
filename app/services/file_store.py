"""
Flat-directory file store shared by certificate and data-package uploads.

Files are stored as ``{file_id}_{safe_original_stem}{suffix}`` so the original
name can be recovered for display without a database row. ``file_id`` is a
16-char hex token; anything else is rejected before it reaches the filesystem
so client input can never act as a glob pattern or path segment.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# New ids are 16 hex chars; legacy ids may be any short token without
# separators, dots, or glob metacharacters.
_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9.-]+")


def is_valid_id(file_id: str) -> bool:
    return bool(_ID_RE.fullmatch(file_id or ""))


def safe_stem(filename: str) -> str:
    """Reduce an uploaded filename to a filesystem-safe stem."""
    stem = Path(filename).stem
    cleaned = _UNSAFE_CHARS.sub("_", stem).strip("._")
    return cleaned[:128] or "file"


class FileStore:
    def __init__(self, root: Path, suffix: str) -> None:
        self.root = root
        self.suffix = suffix

    def _split(self, path: Path) -> tuple[str, str]:
        file_id, _, original = path.stem.partition("_")
        return file_id, (original + self.suffix) if original else path.name

    def list(self) -> list[dict]:
        """Return [{id, filename, size, mtime}] newest first."""
        if not self.root.exists():
            return []
        entries = []
        for path in self.root.glob(f"*{self.suffix}"):
            stat = path.stat()
            file_id, filename = self._split(path)
            entries.append(
                {"id": file_id, "filename": filename, "size": stat.st_size, "mtime": stat.st_mtime}
            )
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        return entries

    def path_for(self, file_id: str) -> Optional[Path]:
        """Resolve an id to its file, or None if the id is invalid or unknown."""
        if not is_valid_id(file_id) or not self.root.exists():
            return None
        for path in self.root.glob(f"{file_id}_*{self.suffix}"):
            return path
        legacy = self.root / f"{file_id}{self.suffix}"
        return legacy if legacy.is_file() else None

    def display_name(self, path: Path) -> str:
        return self._split(path)[1]

    def save(self, filename: str, data: bytes) -> dict:
        """Persist an upload. Returns {id, filename, size}."""
        self.root.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex[:16]
        dest = self.root / f"{file_id}_{safe_stem(filename)}{self.suffix}"
        dest.write_bytes(data)
        log.info("Stored %s as %s", filename, dest.name)
        return {"id": file_id, "filename": filename, "size": len(data)}

    def delete(self, file_id: str) -> bool:
        path = self.path_for(file_id)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        log.info("Deleted %s", path.name)
        return True
