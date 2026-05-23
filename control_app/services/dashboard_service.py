from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_service import ConfigService
from .runtime_service import RuntimeService
from .storage_service import StorageService


class DashboardService:
    def __init__(
        self,
        config_service: ConfigService,
        runtime_service: RuntimeService,
        storage_service: StorageService,
    ) -> None:
        self._config_service = config_service
        self._runtime_service = runtime_service
        self._storage_service = storage_service

    def build_status(self) -> dict[str, Any]:
        runtime = self._runtime_service.snapshot()

        try:
            config = self.build_config_summary(runtime=runtime)
        except Exception as exc:
            config = {
                "path": str(self._config_service.config_path),
                "updated_at": _safe_mtime_iso(self._config_service.config_path),
                "error": str(exc),
                "pending_relaunch": False,
            }

        return {
            "runtime": runtime,
            "config": config,
            "storage": self._storage_service.snapshot(),
        }

    def build_config_summary(
        self,
        config_data: dict[str, Any] | None = None,
        runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config_data = config_data or self._config_service.read_data()
        runtime = runtime or self._runtime_service.snapshot()
        config_mtime = _safe_mtime(self._config_service.config_path)

        pending_relaunch = False
        started_at = runtime.get("started_at_ts")
        if runtime.get("running") and config_mtime is not None and started_at is not None:
            pending_relaunch = config_mtime > started_at

        return {
            "path": str(self._config_service.config_path),
            "updated_at": _safe_mtime_iso(self._config_service.config_path),
            "server_ip": config_data.get("server_ip"),
            "ports": config_data.get("ports", {}),
            "audio": config_data.get("audio", {}),
            "receiver_audio": config_data.get("receiver_audio", {}),
            "video": config_data.get("video", {}),
            "streaming_settings_audio": config_data.get("streaming_settings_audio"),
            "streaming_settings_video": config_data.get("streaming_settings_video"),
            "pending_relaunch": pending_relaunch,
        }


def _safe_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    return path.stat().st_mtime


def _safe_mtime_iso(path: Path) -> str | None:
    mtime = _safe_mtime(path)
    if mtime is None:
        return None
    from .storage_service import _to_iso

    return _to_iso(mtime)
