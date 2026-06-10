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
    storage_reference_root: Path
    recording_dir: Path
    archive_dir: Path
    preview_dir: Path
    runtime_dir: Path
    host_device_root: Path


@dataclass(frozen=True)
class AppSettings:
    paths: AppPaths
    dashboard_username: str
    dashboard_password: str
    central_config_url: str | None
    config_sync_timeout_seconds: float
    log_capacity: int
    python_executable: str


def build_settings() -> AppSettings:
    project_root = Path(__file__).resolve().parents[1]
    storage_root = Path(os.getenv("TBDRIVE_ROOT", "/mnt/tbdrive"))
    storage_reference_root = Path(os.getenv("TBDRIVE_REFERENCE_ROOT", "/config"))
    config_path = _resolve_config_path(project_root)
    paths = AppPaths(
        project_root=project_root,
        static_dir=project_root / "control_app" / "static",
        production_dir=project_root / "production",
        config_path=config_path,
        storage_root=storage_root,
        storage_reference_root=storage_reference_root,
        recording_dir=storage_root,
        archive_dir=storage_root / "video",
        preview_dir=storage_root / "previews",
        runtime_dir=storage_root / "runtime",
        host_device_root=Path(os.getenv("HOST_DEVICE_ROOT", "/host-dev")),
    )

    return AppSettings(
        paths=paths,
        dashboard_username=os.getenv("DASHBOARD_USERNAME", "admin"),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
        central_config_url=_non_empty_env("CENTRAL_CONFIG_URL"),
        config_sync_timeout_seconds=float(os.getenv("CONFIG_SYNC_TIMEOUT_SECONDS", "5")),
        log_capacity=int(os.getenv("LOG_CAPACITY", "500")),
        python_executable=os.getenv("PYTHON_EXECUTABLE", sys.executable),
    )


def _resolve_config_path(project_root: Path) -> Path:
    config_path_override = os.getenv("CONFIG_PATH")
    if config_path_override and config_path_override.strip():
        return Path(config_path_override.strip()).expanduser().resolve()

    shared_config_path = Path("/config/config.yaml")
    shared_config_dir = shared_config_path.parent
    if shared_config_path.exists() or (
        shared_config_dir.is_dir() and os.access(shared_config_dir, os.W_OK)
    ):
        return shared_config_path

    return project_root / "production" / "config.yaml"


def _non_empty_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
