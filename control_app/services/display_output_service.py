from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class DisplayOutputService:
    def __init__(
        self,
        sys_class_drm_root: Path = Path("/sys/class/drm"),
        drm_device_root: Path = Path("/dev/dri"),
    ) -> None:
        self._sys_class_drm_root = sys_class_drm_root
        self._drm_device_root = drm_device_root

    def list_outputs(self) -> list[dict[str, Any]]:
        if not self._sys_class_drm_root.exists():
            return []
        if not self._has_accessible_drm_device():
            return []

        outputs: list[dict[str, Any]] = []
        for path in sorted(self._sys_class_drm_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            if path.name.startswith("render"):
                continue
            if "-" not in path.name:
                continue
            status_path = path / "status"
            if not status_path.exists():
                continue

            connector_id = self._read_connector_id(path)
            if connector_id is None:
                continue

            status = self._read_text(path / "status") or "unknown"
            enabled = self._read_text(path / "enabled") or "unknown"
            modes = self._read_lines(path / "modes")
            outputs.append(
                {
                    "id": str(connector_id),
                    "path": str(connector_id),
                    "label": self._build_label(path.name, status, enabled),
                    "connector": path.name,
                    "status": status,
                    "enabled": enabled,
                    "modes": modes,
                }
            )

        outputs.sort(key=self._sort_key)
        return outputs

    def _has_accessible_drm_device(self) -> bool:
        if not self._drm_device_root.exists():
            return False
        cards = sorted(self._drm_device_root.glob("card*"))
        return any(path.is_char_device() and os.access(path, os.R_OK | os.W_OK) for path in cards)

    def _read_connector_id(self, path: Path) -> int | None:
        for candidate in (path / "connector_id", path / "connector-id"):
            value = self._read_text(candidate)
            if value is None:
                continue
            try:
                return int(value)
            except ValueError:
                continue
        return None

    def _read_text(self, path: Path) -> str | None:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _read_lines(self, path: Path) -> list[str]:
        try:
            return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return []

    def _build_label(self, connector: str, status: str, enabled: str) -> str:
        state_bits = [status]
        if enabled and enabled != status:
            state_bits.append(enabled)
        return f"{connector} ({', '.join(state_bits)})"

    def _sort_key(self, item: dict[str, Any]) -> tuple[int, str]:
        status = str(item.get("status") or "").strip().lower()
        connected_rank = 0 if status == "connected" else 1
        return (connected_rank, str(item.get("connector") or ""))
