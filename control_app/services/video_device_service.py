from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any


VIDEO_DEVICE_PATTERN = re.compile(r"video\d+$")


class VideoDeviceService:
    def __init__(self, host_device_root: Path) -> None:
        self._host_device_root = host_device_root

    def list_devices(self) -> list[dict[str, Any]]:
        root = self._device_root()
        devices: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        by_id_dir = root / "v4l" / "by-id"
        if by_id_dir.exists():
            for alias_path in sorted(by_id_dir.iterdir()):
                try:
                    resolved = alias_path.resolve(strict=True)
                except OSError:
                    continue
                if not self._is_video_device(resolved):
                    continue

                actual_path = str(resolved)
                if actual_path in seen_paths:
                    continue
                seen_paths.add(actual_path)

                devices.append(
                    self._build_entry(
                        actual_path=resolved,
                        alias_path=alias_path,
                        label=self._read_v4l2_label(resolved) or alias_path.name,
                    )
                )

        for device_path in sorted(root.glob("video*")):
            if not self._is_video_device(device_path):
                continue
            actual_path = str(device_path)
            if actual_path in seen_paths:
                continue
            seen_paths.add(actual_path)
            devices.append(
                self._build_entry(
                    actual_path=device_path,
                    alias_path=None,
                    label=self._read_v4l2_label(device_path) or device_path.name,
                )
            )

        return devices

    def _device_root(self) -> Path:
        if self._host_device_root.exists():
            return self._host_device_root
        return Path("/dev")

    def _build_entry(
        self,
        actual_path: Path,
        alias_path: Path | None,
        label: str,
    ) -> dict[str, Any]:
        return {
            "id": str(actual_path),
            "path": str(actual_path),
            "alias_path": str(alias_path) if alias_path is not None else None,
            "label": label,
        }

    def _is_video_device(self, path: Path) -> bool:
        return VIDEO_DEVICE_PATTERN.search(path.name) is not None and path.exists()

    def _read_v4l2_label(self, device_path: Path) -> str | None:
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-D", "-d", str(device_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Card type"):
                _, _, value = stripped.partition(":")
                return value.strip() or None
        return None
