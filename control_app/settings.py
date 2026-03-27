from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppPaths:
    project_root: Path
    static_dir: Path
    production_dir: Path
    config_path: Path
    storage_root: Path
    archive_dir: Path
    preview_dir: Path
    host_device_root: Path


@dataclass(frozen=True)
class AppSettings:
    paths: AppPaths
    dashboard_username: str
    dashboard_password: str
    log_capacity: int
    python_executable: str


def build_settings() -> AppSettings:
    project_root = Path(__file__).resolve().parents[1]
    storage_root = Path(os.getenv("TBDRIVE_ROOT", "/mnt/tbdrive"))
    paths = AppPaths(
        project_root=project_root,
        static_dir=project_root / "control_app" / "static",
        production_dir=project_root / "production",
        config_path=project_root / "production" / "config.yaml",
        storage_root=storage_root,
        archive_dir=storage_root / "video",
        preview_dir=storage_root / "previews",
        host_device_root=Path(os.getenv("HOST_DEVICE_ROOT", "/host-dev")),
    )

    return AppSettings(
        paths=paths,
        dashboard_username=os.getenv("DASHBOARD_USERNAME", "admin"),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
        log_capacity=int(os.getenv("LOG_CAPACITY", "500")),
        python_executable=os.getenv("PYTHON_EXECUTABLE", sys.executable),
    )
