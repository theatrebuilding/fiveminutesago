from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any


VIDEO_DEVICE_PATTERN = re.compile(r"video\d+$")
EXCLUDED_VIDEO_DEVICE_KEYWORDS = ("rpivid", "pispbe")


@dataclass(frozen=True)
class VideoDeviceMetadata:
    label: str | None = None
    driver_name: str | None = None


class VideoDeviceService:
    def __init__(self, host_device_root: Path) -> None:
        self._host_device_root = host_device_root

    def list_devices(self) -> list[dict[str, Any]]:
        root = self._device_root()
        devices: list[dict[str, Any]] = []
        metadata_cache: dict[str, VideoDeviceMetadata] = {}
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
                metadata = self._metadata_for_path(resolved, metadata_cache)
                if self._is_excluded_device(metadata):
                    continue

                devices.append(
                    self._build_entry(
                        actual_path=resolved,
                        alias_path=alias_path,
                        label=metadata.label or alias_path.name,
                    )
                )

        for device_path in sorted(root.glob("video*")):
            if not self._is_video_device(device_path):
                continue
            actual_path = str(device_path)
            if actual_path in seen_paths:
                continue
            seen_paths.add(actual_path)
            metadata = self._metadata_for_path(device_path, metadata_cache)
            if self._is_excluded_device(metadata):
                continue
            devices.append(
                self._build_entry(
                    actual_path=device_path,
                    alias_path=None,
                    label=metadata.label or device_path.name,
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

    def _metadata_for_path(self, device_path: Path, cache: dict[str, VideoDeviceMetadata]) -> VideoDeviceMetadata:
        cache_key = str(device_path)
        metadata = cache.get(cache_key)
        if metadata is not None:
            return metadata

        metadata = self._read_v4l2_metadata(device_path)
        cache[cache_key] = metadata
        return metadata

    def _is_excluded_device(self, metadata: VideoDeviceMetadata) -> bool:
        haystacks = [metadata.label, metadata.driver_name]
        return any(
            keyword in haystack.lower()
            for haystack in haystacks
            if haystack
            for keyword in EXCLUDED_VIDEO_DEVICE_KEYWORDS
        )

    def _read_v4l2_metadata(self, device_path: Path) -> VideoDeviceMetadata:
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-D", "-d", str(device_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return VideoDeviceMetadata()

        if result.returncode != 0:
            return VideoDeviceMetadata()

        label = None
        driver_name = None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Driver name"):
                _, _, value = stripped.partition(":")
                driver_name = value.strip() or None
            if stripped.startswith("Card type"):
                _, _, value = stripped.partition(":")
                label = value.strip() or None

        return VideoDeviceMetadata(label=label, driver_name=driver_name)
