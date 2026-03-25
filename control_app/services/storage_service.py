from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any


class StorageService:
    def __init__(self, storage_root: Path, archive_dir: Path) -> None:
        self._storage_root = storage_root
        self._archive_dir = archive_dir

    def snapshot(self) -> dict[str, Any]:
        working_files = [
            self._describe_file(self._storage_root / "video_tn.ts"),
            self._describe_file(self._storage_root / "video_dk.ts"),
        ]
        archive = self._describe_archive_dir()
        return {
            "storage_root": str(self._storage_root),
            "working_files": working_files,
            "archive": archive,
        }

    def _describe_archive_dir(self) -> dict[str, Any]:
        if not self._archive_dir.exists():
            return {
                "path": str(self._archive_dir),
                "exists": False,
                "file_count": 0,
                "total_size_bytes": 0,
                "latest_files": [],
            }

        files = [path for path in self._archive_dir.iterdir() if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

        return {
            "path": str(self._archive_dir),
            "exists": True,
            "file_count": len(files),
            "total_size_bytes": sum(path.stat().st_size for path in files),
            "latest_files": [self._describe_file(path) for path in files[:5]],
        }

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


def _to_iso(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
