from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any


ARCHIVE_MEDIA_SUFFIXES = {".ts", ".mp4"}


class StorageService:
    def __init__(
        self,
        storage_root: Path,
        archive_dir: Path,
        storage_reference_root: Path | None = None,
    ) -> None:
        self._storage_root = storage_root
        self._archive_dir = archive_dir
        self._storage_reference_root = storage_reference_root

    def snapshot(self) -> dict[str, Any]:
        root = self._describe_storage_root()
        return {
            "storage_root": str(self._storage_root),
            "root": root,
            "warning": root.get("warning"),
            "archive": self._describe_archive_dir(),
        }

    def _describe_storage_root(self) -> dict[str, Any]:
        exists = self._storage_root.exists()
        is_directory = self._storage_root.is_dir() if exists else False
        writable = os.access(self._storage_root, os.W_OK) if exists else False
        warning = None
        separate_from_reference_filesystem = None

        if not exists:
            warning = f"Storage root {self._storage_root} does not exist inside the container."
        elif not is_directory:
            warning = f"Storage root {self._storage_root} is not a directory."
        else:
            separate_from_reference_filesystem = self._detect_separate_storage_filesystem()
            if not writable:
                warning = f"Storage root {self._storage_root} is not writable."
            elif separate_from_reference_filesystem is False:
                warning = (
                    f"Storage root {self._storage_root} looks like ordinary local storage, not the mounted TB drive. "
                    "Recordings may not persist on the external drive until the host mounts it there."
                )

        return {
            "path": str(self._storage_root),
            "exists": exists,
            "is_directory": is_directory,
            "writable": writable,
            "reference_path": str(self._storage_reference_root) if self._storage_reference_root is not None else None,
            "separate_from_reference_filesystem": separate_from_reference_filesystem,
            "warning": warning,
        }

    def _detect_separate_storage_filesystem(self) -> bool | None:
        if self._storage_reference_root is None:
            return None
        if not self._storage_root.exists() or not self._storage_reference_root.exists():
            return None
        try:
            storage_dev = self._storage_root.stat().st_dev
            reference_dev = self._storage_reference_root.stat().st_dev
        except OSError:
            return None
        return storage_dev != reference_dev

    def _describe_archive_dir(self) -> dict[str, Any]:
        if not self._archive_dir.exists():
            return {
                "path": str(self._archive_dir),
                "exists": False,
                "file_count": 0,
                "total_size_bytes": 0,
                "latest_files": [],
            }

        files = [
            path
            for path in self._archive_dir.iterdir()
            if path.is_file() and self._is_archive_media(path)
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

        return {
            "path": str(self._archive_dir),
            "exists": True,
            "file_count": len(files),
            "total_size_bytes": sum(path.stat().st_size for path in files),
            "latest_files": [self._describe_file(path) for path in files],
        }

    def get_archive_file(self, filename: str) -> Path | None:
        candidate = (self._archive_dir / filename).resolve()
        archive_root = self._archive_dir.resolve()
        try:
            candidate.relative_to(archive_root)
        except ValueError:
            return None
        if not candidate.exists() or not candidate.is_file() or not self._is_archive_media(candidate):
            return None
        return candidate

    def media_type_for(self, path: Path) -> str:
        if path.suffix.lower() == ".mp4":
            return "video/mp4"
        if path.suffix.lower() == ".ts":
            return "video/mp2t"
        return "application/octet-stream"

    def _describe_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {
                "name": path.name,
                "path": str(path),
                "exists": False,
                "size_bytes": 0,
                "modified_at": None,
                "modified_at_ts": None,
                "age_seconds": None,
                "fresh": False,
            }

        stat = path.stat()
        modified_at = stat.st_mtime
        age_seconds = max(0, int(dt.datetime.now().timestamp() - modified_at))
        return {
            "name": path.name,
            "path": str(path),
            "exists": True,
            "size_bytes": stat.st_size,
            "modified_at": _to_iso(modified_at),
            "modified_at_ts": modified_at,
            "age_seconds": age_seconds,
            "fresh": age_seconds < 15,
        }

    def _is_archive_media(self, path: Path) -> bool:
        return path.suffix.lower() in ARCHIVE_MEDIA_SUFFIXES and not path.name.endswith(".recording.ts")


def _to_iso(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
