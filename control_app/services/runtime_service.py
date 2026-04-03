from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import datetime as dt
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

from .preview_catalog import (
    build_receiver_preview_pattern,
    build_sender_preview_pattern,
    describe_latest_preview,
    prune_preview_files,
)
from .server_runtime import ServerRuntime


VALID_ROLES = {"server", "sender", "receiver"}
VALID_COUNTRIES = {"tn", "dk"}
VALID_SENDER_AUDIO_SOURCES = {"off", "device", "test"}
VALID_SENDER_AUDIO_MODES = {"aec", "capture-only"}
VALID_SENDER_VIDEO_SOURCES = {"config", "device", "test"}
VALID_RECEIVER_AUDIO_TRANSPORTS = {"config", "off", "aac"}


@dataclass(frozen=True)
class RuntimeLaunchRequest:
    role: str
    country: str | None = None
    audio_source: str = "off"
    sender_audio_mode: str = "aec"
    audio_device: str | None = None
    video_source: str = "test"
    video_device: str | None = None
    receiver_audio_transport: str = "config"

    @property
    def audio_enabled(self) -> bool:
        return self.role == "sender" and self.audio_source != "off"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "country": self.country,
            "audio_enabled": self.audio_enabled,
            "audio_source": self.audio_source,
            "sender_audio_mode": self.sender_audio_mode,
            "audio_device": self.audio_device,
            "video_source": self.video_source,
            "video_device": self.video_device,
            "receiver_audio_transport": self.receiver_audio_transport,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RuntimeLaunchRequest":
        role = str(payload.get("role") or "").strip().lower()
        if role not in VALID_ROLES:
            raise ValueError("Role must be one of: server, sender, receiver.")

        country_raw = payload.get("country")
        country = None
        if country_raw is not None and str(country_raw).strip():
            country = str(country_raw).strip().lower()

        if role in {"sender", "receiver"} and country not in VALID_COUNTRIES:
            raise ValueError("Sender and receiver require country to be 'tn' or 'dk'.")
        if role == "server":
            country = None

        audio_source_raw = payload.get("audio_source")
        audio_source = str(audio_source_raw).strip().lower() if audio_source_raw is not None else ""
        if not audio_source:
            audio_source = "device" if bool(payload.get("audio_enabled")) else "off"
        if audio_source not in VALID_SENDER_AUDIO_SOURCES:
            raise ValueError("Sender audio source must be one of: off, device, test.")
        sender_audio_mode_raw = payload.get("sender_audio_mode")
        sender_audio_mode = str(sender_audio_mode_raw).strip().lower() if sender_audio_mode_raw is not None else "aec"
        if sender_audio_mode not in VALID_SENDER_AUDIO_MODES:
            raise ValueError("Sender audio mode must be one of: aec, capture-only.")

        audio_device_raw = payload.get("audio_device")
        audio_device = str(audio_device_raw).strip() or None if audio_device_raw is not None else None
        video_device_raw = payload.get("video_device")
        video_device = str(video_device_raw).strip() or None if video_device_raw is not None else None
        video_source_raw = payload.get("video_source")
        video_source = str(video_source_raw).strip().lower() if video_source_raw is not None else ""
        if not video_source:
            video_source = "device" if video_device else "test"
        if video_source not in VALID_SENDER_VIDEO_SOURCES:
            raise ValueError("Sender video source must be one of: config, device, test.")
        receiver_audio_transport_raw = payload.get("receiver_audio_transport")
        receiver_audio_transport = (
            str(receiver_audio_transport_raw).strip().lower()
            if receiver_audio_transport_raw is not None
            else "config"
        )
        if receiver_audio_transport == "pcm":
            receiver_audio_transport = "aac"
        if receiver_audio_transport not in VALID_RECEIVER_AUDIO_TRANSPORTS:
            raise ValueError("Receiver audio transport must be one of: config, off, aac.")

        if role != "sender":
            audio_source = "off"
            sender_audio_mode = "aec"
            audio_device = None
            video_source = "config"
            video_device = None
        else:
            if audio_source != "device":
                audio_device = None
            if video_source != "device":
                video_device = None
            elif video_device is None:
                raise ValueError("Sender video source 'device' requires a video device path.")

        if role != "receiver":
            receiver_audio_transport = "config"

        return cls(
            role=role,
            country=country,
            audio_source=audio_source,
            sender_audio_mode=sender_audio_mode,
            audio_device=audio_device,
            video_source=video_source,
            video_device=video_device,
            receiver_audio_transport=receiver_audio_transport,
        )


class RuntimeService:
    def __init__(
        self,
        python_executable: str,
        project_root: Path,
        config_path: Path,
        recording_dir: Path,
        archive_dir: Path,
        preview_dir: Path,
        log_capacity: int = 500,
    ) -> None:
        self._python_executable = python_executable
        self._project_root = project_root
        self._config_path = config_path
        self._recording_dir = recording_dir
        self._archive_dir = archive_dir
        self._preview_dir = preview_dir
        self._log_capacity = log_capacity

        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._server_runtime: ServerRuntime | None = None
        self._current_request: RuntimeLaunchRequest | None = None
        self._log_lines: deque[str] = deque(maxlen=log_capacity)
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_exit_code: int | None = None

    def start(self, request: RuntimeLaunchRequest) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self._log_lines.clear()

        if request.role == "server":
            runtime = ServerRuntime(
                config_path=self._config_path,
                recording_dir=self._recording_dir,
                archive_dir=self._archive_dir,
                preview_dir=self._preview_dir,
                log_callback=self.record_event,
            )
            runtime.start()
            with self._lock:
                self._server_runtime = runtime
                self._current_request = request
                self._started_at = time.time()
                self._stopped_at = None
                self._last_exit_code = None
        else:
            command, working_dir = self._build_process_command(request)
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                command,
                cwd=working_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._process = process
                self._current_request = request
                self._started_at = time.time()
                self._stopped_at = None
                self._last_exit_code = None
            threading.Thread(
                target=self._drain_output,
                args=(process,),
                daemon=True,
                name="runtime-log-reader",
            ).start()
            threading.Thread(
                target=self._watch_process,
                args=(process,),
                daemon=True,
                name="runtime-process-watcher",
            ).start()

        self.record_event(f"{request.role.title()} role started.")
        return self.snapshot()

    def stop(self, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            self._sync_state_locked()
            process = self._process
            runtime = self._server_runtime

        if process is None and runtime is None:
            return self.snapshot()

        if runtime is not None:
            self.record_event(f"Stopping {self._current_request.role if self._current_request else 'server'} role...")
            runtime.stop()
            with self._lock:
                if self._server_runtime is runtime:
                    self._server_runtime = None
                    self._stopped_at = time.time()
                    self._last_exit_code = runtime.snapshot().get("last_exit_code", 0)
            return self.snapshot()

        assert process is not None
        self.record_event(f"Stopping {self._current_request.role if self._current_request else 'process'} role...")
        process.terminate()
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.record_event("Role process did not stop in time. Killing process.")
            process.kill()
            exit_code = process.wait(timeout=5)

        self._record_exit(process, exit_code)
        return self.snapshot()

    def relaunch_active(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        if not snapshot["running"] or self._current_request is None:
            return snapshot
        return self.start(self._current_request)

    def start_recording(self) -> dict[str, Any]:
        with self._lock:
            runtime = self._server_runtime
            request = self._current_request
        if runtime is None or request is None or request.role != "server":
            raise RuntimeError("Recording controls are only available while the server role is running.")
        runtime.start_recording()
        self.record_event("Recording started from dashboard.")
        return self.snapshot()

    def stop_recording(self) -> dict[str, Any]:
        with self._lock:
            runtime = self._server_runtime
            request = self._current_request
        if runtime is None or request is None or request.role != "server":
            raise RuntimeError("Recording controls are only available while the server role is running.")
        runtime.stop_recording()
        self.record_event("Recording stopped from dashboard.")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._sync_state_locked()
            request = self._current_request
            server = self._server_runtime.snapshot() if self._server_runtime is not None else None
            sender = self._build_sender_snapshot_locked(request)
            receiver = self._build_receiver_snapshot_locked(request)
            running = self._process is not None or (server is not None and server.get("running"))
            return {
                "running": running,
                "role": request.role if request is not None else None,
                "launch": request.to_dict() if request is not None else None,
                "started_at": _to_iso(self._started_at),
                "started_at_ts": self._started_at,
                "stopped_at": _to_iso(self._stopped_at),
                "stopped_at_ts": self._stopped_at,
                "uptime_seconds": int(time.time() - self._started_at) if running and self._started_at else None,
                "last_exit_code": self._last_exit_code,
                "pid": self._process.pid if self._process is not None else None,
                "log_tail": list(self._log_lines),
                "server": server,
                "sender": sender,
                "receiver": receiver,
            }

    def record_event(self, message: str) -> None:
        timestamp = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._log_lines.append(f"[control {timestamp}] {message}")

    def _build_process_command(self, request: RuntimeLaunchRequest) -> tuple[list[str], Path]:
        if request.role == "sender":
            self._preview_dir.mkdir(parents=True, exist_ok=True)
            preview_pattern = build_sender_preview_pattern(self._preview_dir, request.country or "tn")
            prune_preview_files(self._preview_dir, preview_pattern, keep=0)
            command = [self._python_executable, "send.py", "--country", request.country or "tn"]
            if request.audio_enabled:
                command.extend(
                    [
                        "--with-audio",
                        "--audio-source",
                        request.audio_source,
                        "--sender-audio-mode",
                        request.sender_audio_mode,
                    ]
                )
            else:
                command.append("--no-audio")
            if request.audio_source == "device" and request.audio_device:
                command.extend(["--device", request.audio_device])
            if request.video_source == "device" and request.video_device:
                command.extend(["--video-device", request.video_device])
            else:
                command.extend(["--video-source", request.video_source])
            command.extend(["--preview-pattern", preview_pattern])
            working_dir = self._project_root / "production" / "1_sender"
            return command, working_dir

        if request.role == "receiver":
            self._preview_dir.mkdir(parents=True, exist_ok=True)
            preview_pattern = build_receiver_preview_pattern(self._preview_dir, request.country or "tn")
            prune_preview_files(self._preview_dir, preview_pattern, keep=0)
            command = [
                self._python_executable,
                "receive.py",
                "--country",
                request.country or "tn",
                "--audio-transport",
                request.receiver_audio_transport,
                "--preview-pattern",
                preview_pattern,
            ]
            working_dir = self._project_root / "production" / "3_receiver"
            return command, working_dir

        raise ValueError(f"Unsupported subprocess role: {request.role}")

    def _build_sender_snapshot_locked(self, request: RuntimeLaunchRequest | None) -> dict[str, Any] | None:
        if request is None or request.role != "sender" or request.country is None:
            return None

        preview_pattern = build_sender_preview_pattern(self._preview_dir, request.country)
        return {
            "country": request.country,
            "preview": describe_latest_preview(self._preview_dir, preview_pattern),
        }

    def _build_receiver_snapshot_locked(self, request: RuntimeLaunchRequest | None) -> dict[str, Any] | None:
        if request is None or request.role != "receiver" or request.country is None:
            return None

        preview_pattern = build_receiver_preview_pattern(self._preview_dir, request.country)
        return {
            "country": request.country,
            "preview": describe_latest_preview(self._preview_dir, preview_pattern),
        }

    def _drain_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        for line in process.stdout:
            cleaned = line.rstrip()
            if not cleaned:
                continue
            with self._lock:
                self._log_lines.append(cleaned)

    def _watch_process(self, process: subprocess.Popen[str]) -> None:
        exit_code = process.wait()
        self._record_exit(process, exit_code)

    def _record_exit(self, process: subprocess.Popen[str], exit_code: int) -> None:
        should_log = False
        with self._lock:
            if self._process is process:
                self._process = None
                self._last_exit_code = exit_code
                self._stopped_at = time.time()
                should_log = True
            elif self._last_exit_code is None:
                self._last_exit_code = exit_code
                self._stopped_at = self._stopped_at or time.time()

        if should_log:
            self.record_event(f"Role process exited with code {exit_code}.")

    def _sync_state_locked(self) -> None:
        if self._process is not None:
            exit_code = self._process.poll()
            if exit_code is not None:
                self._process = None
                self._last_exit_code = exit_code
                self._stopped_at = self._stopped_at or time.time()

        if self._server_runtime is not None:
            server_snapshot = self._server_runtime.snapshot()
            if not server_snapshot.get("running"):
                self._last_exit_code = server_snapshot.get("last_exit_code")
                self._stopped_at = self._stopped_at or time.time()
                self._server_runtime = None


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
