from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_service import ConfigService
from .relay_supervisor import RelaySupervisor
from .storage_service import StorageService


class DashboardService:
    def __init__(
        self,
        config_service: ConfigService,
        relay_supervisor: RelaySupervisor,
        storage_service: StorageService,
    ) -> None:
        self._config_service = config_service
        self._relay_supervisor = relay_supervisor
        self._storage_service = storage_service

    def build_status(self) -> dict[str, Any]:
        relay = self._relay_supervisor.snapshot()

        try:
            config_data = self._config_service.read_data()
            config = self.build_config_summary(config_data, relay)
        except Exception as exc:
            config = {
                "path": str(self._config_service.config_path),
                "updated_at": _safe_mtime_iso(self._config_service.config_path),
                "error": str(exc),
                "pending_restart": False,
            }

        return {
            "relay": relay,
            "config": config,
            "storage": self._storage_service.snapshot(),
        }

    def build_config_summary(
        self,
        config_data: dict[str, Any] | None = None,
        relay: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config_data = config_data or self._config_service.read_data()
        relay = relay or self._relay_supervisor.snapshot()
        config_mtime = _safe_mtime(self._config_service.config_path)

        pending_restart = False
        started_at = relay.get("started_at_ts")
        if relay.get("running") and config_mtime is not None and started_at is not None:
            pending_restart = config_mtime > started_at

        return {
            "path": str(self._config_service.config_path),
            "updated_at": _safe_mtime_iso(self._config_service.config_path),
            "server_ip": config_data.get("server_ip"),
            "ports": config_data.get("ports", {}),
            "audio": config_data.get("audio", {}),
            "video": config_data.get("video", {}),
            "streaming_settings_audio": config_data.get("streaming_settings_audio"),
            "streaming_settings_video": config_data.get("streaming_settings_video"),
            "pending_restart": pending_restart,
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
