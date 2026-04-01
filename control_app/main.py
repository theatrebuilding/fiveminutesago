from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .services.config_service import ConfigService, ConfigValidationError
from .services.audio_device_service import AudioDeviceService
from .services.dashboard_service import DashboardService
from .services.runtime_service import RuntimeLaunchRequest, RuntimeService
from .services.storage_service import StorageService
from .services.video_device_service import VideoDeviceService
from .settings import AppSettings, build_settings


@dataclass(frozen=True)
class AppServices:
    settings: AppSettings
    config_service: ConfigService
    runtime_service: RuntimeService
    dashboard_service: DashboardService
    storage_service: StorageService
    audio_device_service: AudioDeviceService
    video_device_service: VideoDeviceService


settings = build_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_service = ConfigService(settings.paths.config_path)
    runtime_service = RuntimeService(
        python_executable=settings.python_executable,
        project_root=settings.paths.project_root,
        config_path=settings.paths.config_path,
        recording_dir=settings.paths.recording_dir,
        archive_dir=settings.paths.archive_dir,
        preview_dir=settings.paths.preview_dir,
        log_capacity=settings.log_capacity,
    )
    storage_service = StorageService(
        storage_root=settings.paths.storage_root,
        archive_dir=settings.paths.archive_dir,
        storage_reference_root=settings.paths.storage_reference_root,
    )
    dashboard_service = DashboardService(
        config_service=config_service,
        runtime_service=runtime_service,
        storage_service=storage_service,
    )
    audio_device_service = AudioDeviceService()
    video_device_service = VideoDeviceService(settings.paths.host_device_root)

    app.state.services = AppServices(
        settings=settings,
        config_service=config_service,
        runtime_service=runtime_service,
        dashboard_service=dashboard_service,
        storage_service=storage_service,
        audio_device_service=audio_device_service,
        video_device_service=video_device_service,
    )

    yield

    runtime_service.stop()


app = FastAPI(title="Five Minutes Ago Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.paths.static_dir)), name="static")


@app.middleware("http")
async def basic_auth_guard(request: Request, call_next):
    if not settings.dashboard_password:
        return await call_next(request)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return _unauthorized()

    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return _unauthorized()

    if username != settings.dashboard_username:
        return _unauthorized()

    if not secrets.compare_digest(password, settings.dashboard_password):
        return _unauthorized()

    return await call_next(request)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        settings.paths.static_dir / "index.html",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/status")
async def get_status(request: Request) -> dict[str, Any]:
    return _services(request).dashboard_service.build_status()


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    services = _services(request)
    return {
        "path": str(services.config_service.config_path),
        "text": services.config_service.read_text(),
        "summary": services.dashboard_service.build_config_summary(),
    }


@app.get("/api/devices/video")
async def get_video_devices(request: Request) -> dict[str, Any]:
    services = _services(request)
    return {
        "devices": services.video_device_service.list_devices(),
        "root": str(services.settings.paths.host_device_root),
    }


@app.get("/api/devices/audio")
async def get_audio_devices(request: Request) -> dict[str, Any]:
    services = _services(request)
    return {
        "devices": services.audio_device_service.list_devices(),
    }


@app.put("/api/config")
async def update_config(request: Request) -> dict[str, Any]:
    payload = await request.json()
    text = payload.get("text")
    restart = bool(payload.get("restart"))

    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Config text is required.")

    services = _services(request)

    try:
        parsed = services.config_service.write_text(text)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    services.runtime_service.record_event("Configuration updated from dashboard.")

    runtime_status = services.runtime_service.snapshot()
    if restart:
        runtime_status = services.runtime_service.relaunch_active()

    return {
        "message": "Configuration saved and active role relaunched." if restart and runtime_status.get("running") else "Configuration saved.",
        "runtime": runtime_status,
        "summary": services.dashboard_service.build_config_summary(parsed, runtime_status),
    }


@app.post("/api/runtime/start")
async def runtime_start(request: Request) -> dict[str, Any]:
    services = _services(request)
    payload = await request.json()

    try:
        launch_request = RuntimeLaunchRequest.from_payload(payload)
        status = services.runtime_service.start(launch_request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"message": f"{launch_request.role.title()} started.", "runtime": status}


@app.post("/api/runtime/stop")
async def runtime_stop(request: Request) -> dict[str, Any]:
    services = _services(request)
    status = services.runtime_service.stop()
    return {"message": "Active role stopped.", "runtime": status}


@app.post("/api/server/recording/{action}")
async def server_recording_action(action: str, request: Request) -> dict[str, Any]:
    services = _services(request)

    try:
        if action == "start":
            status = services.runtime_service.start_recording()
            message = "Recording started."
        elif action == "stop":
            status = services.runtime_service.stop_recording()
            message = "Recording stopped."
        else:
            raise HTTPException(status_code=404, detail="Unknown recording action.")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"message": message, "runtime": status}


@app.get("/api/server/preview/{feed}.jpg")
async def server_preview(feed: str, request: Request) -> FileResponse:
    feed = feed.strip().lower()
    if feed not in {"tn", "dk"}:
        raise HTTPException(status_code=404, detail="Unknown preview feed.")

    services = _services(request)
    runtime = services.runtime_service.snapshot()
    server = runtime.get("server") or {}
    previews = server.get("previews") or {}
    path = (previews.get(feed) or {}).get("path")
    if not path:
        raise HTTPException(status_code=404, detail="Preview not available.")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/receiver/preview.jpg")
async def receiver_preview(request: Request) -> FileResponse:
    services = _services(request)
    runtime = services.runtime_service.snapshot()
    receiver = runtime.get("receiver") or {}
    path = (receiver.get("preview") or {}).get("path")
    if not path:
        raise HTTPException(status_code=404, detail="Preview not available.")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/sender/preview.jpg")
async def sender_preview(request: Request) -> FileResponse:
    services = _services(request)
    runtime = services.runtime_service.snapshot()
    sender = runtime.get("sender") or {}
    path = (sender.get("preview") or {}).get("path")
    if not path:
        raise HTTPException(status_code=404, detail="Preview not available.")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/archive/files/{filename}")
async def archive_file(filename: str, request: Request) -> FileResponse:
    services = _services(request)
    path = services.storage_service.get_archive_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Archive file not available.")

    return FileResponse(
        path,
        media_type=services.storage_service.media_type_for(path),
        filename=path.name,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Disposition": _content_disposition("inline", path.name),
        },
    )


@app.get("/api/archive/files/{filename}/download")
async def archive_file_download(filename: str, request: Request) -> FileResponse:
    services = _services(request)
    path = services.storage_service.get_archive_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Archive file not available.")

    return FileResponse(
        path,
        media_type=services.storage_service.media_type_for(path),
        filename=path.name,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Disposition": _content_disposition("attachment", path.name),
        },
    )


@app.post("/api/archive/files/{filename}/rename")
async def rename_archive_file(filename: str, request: Request) -> dict[str, Any]:
    services = _services(request)
    payload = await request.json()
    base_name = payload.get("base_name")
    if not isinstance(base_name, str):
        raise HTTPException(status_code=400, detail="A new file name is required.")

    try:
        file_info = services.storage_service.rename_archive_file(filename, base_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    services.runtime_service.record_event(f"Archive file renamed: {filename} -> {file_info['name']}.")
    return {
        "message": f"Renamed archive file to {file_info['name']}.",
        "file": file_info,
        "storage": services.storage_service.snapshot(),
    }


@app.delete("/api/archive/files/{filename}")
async def delete_archive_file(filename: str, request: Request) -> dict[str, Any]:
    services = _services(request)

    try:
        services.storage_service.delete_archive_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    services.runtime_service.record_event(f"Archive file deleted: {filename}.")
    return {
        "message": f"Deleted archive file {filename}.",
        "storage": services.storage_service.snapshot(),
    }


def _services(request: Request) -> AppServices:
    return request.app.state.services


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required."},
        headers={"WWW-Authenticate": 'Basic realm="Five Minutes Ago"'},
    )


def _content_disposition(disposition_type: str, filename: str) -> str:
    ascii_fallback = filename.replace("\\", "_").replace('"', "")
    return f"{disposition_type}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
