from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .services.config_service import ConfigService, ConfigValidationError
from .services.dashboard_service import DashboardService
from .services.relay_supervisor import RelaySupervisor
from .services.storage_service import StorageService
from .settings import AppSettings, build_settings


@dataclass(frozen=True)
class AppServices:
    settings: AppSettings
    config_service: ConfigService
    relay_supervisor: RelaySupervisor
    dashboard_service: DashboardService


settings = build_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_service = ConfigService(settings.paths.config_path)
    relay_supervisor = RelaySupervisor(
        python_executable=settings.python_executable,
        working_dir=settings.paths.relay_dir,
        log_capacity=settings.log_capacity,
    )
    storage_service = StorageService(
        storage_root=settings.paths.storage_root,
        archive_dir=settings.paths.archive_dir,
    )
    dashboard_service = DashboardService(
        config_service=config_service,
        relay_supervisor=relay_supervisor,
        storage_service=storage_service,
    )

    app.state.services = AppServices(
        settings=settings,
        config_service=config_service,
        relay_supervisor=relay_supervisor,
        dashboard_service=dashboard_service,
    )

    if settings.auto_start_relay:
        try:
            relay_supervisor.start()
        except Exception as exc:  # pragma: no cover - startup failures are surfaced in UI/logs
            relay_supervisor.record_event(f"Auto-start failed: {exc}")

    yield

    relay_supervisor.stop()


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
    return FileResponse(settings.paths.static_dir / "index.html")


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

    services.relay_supervisor.record_event("Configuration updated from dashboard.")

    relay_status = services.relay_supervisor.snapshot()
    if restart:
        relay_status = services.relay_supervisor.restart_or_start()

    return {
        "message": "Configuration saved and relay reloaded." if restart else "Configuration saved.",
        "relay": relay_status,
        "summary": services.dashboard_service.build_config_summary(parsed, relay_status),
    }


@app.post("/api/relay/{action}")
async def relay_action(action: str, request: Request) -> dict[str, Any]:
    services = _services(request)

    if action == "start":
        status = services.relay_supervisor.start()
        message = "Relay started."
    elif action == "stop":
        status = services.relay_supervisor.stop()
        message = "Relay stopped."
    elif action == "restart":
        status = services.relay_supervisor.restart_or_start()
        message = "Relay restarted."
    else:
        raise HTTPException(status_code=404, detail="Unknown relay action.")

    return {"message": message, "relay": status}


def _services(request: Request) -> AppServices:
    return request.app.state.services


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required."},
        headers={"WWW-Authenticate": 'Basic realm="Five Minutes Ago"'},
    )
