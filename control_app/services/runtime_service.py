from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import datetime as dt
import os
from pathlib import Path
import signal
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any

import yaml

from .preview_catalog import (
    build_receiver_preview_pattern,
    build_sender_preview_pattern,
    describe_latest_preview,
    prune_preview_files,
)
from .server_runtime import ServerRuntime
from .sender_recovery import (
    CAPTURE_ONLY_MODE,
    DEGRADED_PHASE,
    PLAYBACK_DSP_MODE,
    RESTORING_PHASE,
    RecoveryAction,
    SenderRecoveryPolicy,
    VIDEO_ONLY_MODE,
    sender_mode_for_request,
    video_only_request,
)
from production.audio_support import (
    alsa_runtime_device,
    build_output_pair_mix_element,
    normalize_audio_channel_pair,
    normalize_audio_hardware_channels,
    validate_local_audio_rate,
)


VALID_ROLES = {"server", "sender", "receiver"}
VALID_COUNTRIES = {"tn", "dk"}
VALID_SENDER_AUDIO_SOURCES = {"off", "device", "test"}
VALID_SENDER_AUDIO_MODES = {"aec", "capture-only"}
VALID_SENDER_VIDEO_SOURCES = {"config", "device", "test"}
VALID_RECEIVER_AUDIO_TRANSPORTS = {"config", "off", "aac", "l16"}
MAX_SYNC_DELAY_MS = 3000
SENDER_HEALTH_CHECK_INTERVAL_SECONDS = 5.0
SENDER_PREVIEW_STALE_SECONDS = 20.0


@dataclass(frozen=True)
class RuntimeLaunchRequest:
    role: str
    country: str | None = None
    audio_source: str = "off"
    sender_audio_mode: str = "aec"
    audio_device: str | None = None
    sender_playback_device: str | None = None
    sender_audio_rate: int | None = None
    sender_capture_input_channels: tuple[int, int] = (1, 2)
    sender_capture_hardware_channels: int = 2
    sender_playback_output_channels: tuple[int, int] = (1, 2)
    sender_playback_hardware_channels: int = 2
    video_source: str = "test"
    video_device: str | None = None
    sender_audio_delay_ms: int = 0
    receiver_audio_transport: str = "off"
    receiver_playback_device: str | None = None
    receiver_video_output: str | None = None
    receiver_video_delay_ms: int = 0

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
            "sender_playback_device": self.sender_playback_device,
            "sender_audio_rate": self.sender_audio_rate,
            "sender_capture_input_channels": list(self.sender_capture_input_channels),
            "sender_capture_hardware_channels": self.sender_capture_hardware_channels,
            "sender_playback_output_channels": list(self.sender_playback_output_channels),
            "sender_playback_hardware_channels": self.sender_playback_hardware_channels,
            "video_source": self.video_source,
            "video_device": self.video_device,
            "sender_audio_delay_ms": self.sender_audio_delay_ms,
            "receiver_audio_transport": self.receiver_audio_transport,
            "receiver_playback_device": self.receiver_playback_device,
            "receiver_video_output": self.receiver_video_output,
            "receiver_video_delay_ms": self.receiver_video_delay_ms,
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
        sender_playback_device_raw = payload.get("sender_playback_device")
        sender_playback_device = (
            str(sender_playback_device_raw).strip() or None
            if sender_playback_device_raw is not None
            else None
        )
        sender_audio_rate = _parse_optional_audio_rate(payload.get("sender_audio_rate"))
        sender_capture_input_channels = _parse_channel_pair(
            payload.get("sender_capture_input_channels", [1, 2]),
            "sender_capture_input_channels",
        )
        sender_capture_hardware_channels = _parse_hardware_channels(
            payload.get("sender_capture_hardware_channels"),
            sender_capture_input_channels,
            "sender_capture_hardware_channels",
        )
        sender_playback_output_channels = _parse_channel_pair(
            payload.get("sender_playback_output_channels", [1, 2]),
            "sender_playback_output_channels",
        )
        sender_playback_hardware_channels = _parse_hardware_channels(
            payload.get("sender_playback_hardware_channels"),
            sender_playback_output_channels,
            "sender_playback_hardware_channels",
        )
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
            else "off"
        )
        if receiver_audio_transport in {"pcm", "uncompressed"}:
            receiver_audio_transport = "l16"
        if receiver_audio_transport == "muxed":
            receiver_audio_transport = "aac"
        if receiver_audio_transport not in VALID_RECEIVER_AUDIO_TRANSPORTS:
            raise ValueError("Receiver audio transport must be one of: config, off, aac, l16.")
        sender_audio_delay_ms = _parse_sync_delay_ms(
            payload.get("sender_audio_delay_ms", 0),
            "sender_audio_delay_ms",
        )
        receiver_video_delay_ms = _parse_sync_delay_ms(
            payload.get("receiver_video_delay_ms", 0),
            "receiver_video_delay_ms",
        )
        receiver_playback_device_raw = payload.get("receiver_playback_device")
        receiver_playback_device = (
            str(receiver_playback_device_raw).strip() or None
            if receiver_playback_device_raw is not None
            else None
        )
        receiver_video_output_raw = payload.get("receiver_video_output")
        receiver_video_output = (
            str(receiver_video_output_raw).strip() or None
            if receiver_video_output_raw is not None
            else None
        )

        if role != "sender":
            audio_source = "off"
            sender_audio_mode = "aec"
            audio_device = None
            sender_playback_device = None
            sender_audio_rate = None
            sender_capture_input_channels = (1, 2)
            sender_capture_hardware_channels = 2
            sender_playback_output_channels = (1, 2)
            sender_playback_hardware_channels = 2
            video_source = "config"
            video_device = None
            sender_audio_delay_ms = 0
        else:
            if audio_source != "device":
                audio_device = None
                sender_capture_input_channels = (1, 2)
                sender_capture_hardware_channels = 2
            if sender_audio_mode != "aec" or audio_source == "off":
                sender_playback_device = None
                sender_audio_delay_ms = 0
                sender_playback_output_channels = (1, 2)
                sender_playback_hardware_channels = 2
            if audio_source == "off":
                sender_audio_rate = None
            if video_source != "device":
                video_device = None
            elif video_device is None:
                raise ValueError("Sender video source 'device' requires a video device path.")

        if role != "receiver":
            receiver_audio_transport = "off"
            receiver_playback_device = None
            receiver_video_output = None
            receiver_video_delay_ms = 0
        elif receiver_audio_transport == "off":
            receiver_playback_device = None

        return cls(
            role=role,
            country=country,
            audio_source=audio_source,
            sender_audio_mode=sender_audio_mode,
            audio_device=audio_device,
            sender_playback_device=sender_playback_device,
            sender_audio_rate=sender_audio_rate,
            sender_capture_input_channels=sender_capture_input_channels,
            sender_capture_hardware_channels=sender_capture_hardware_channels,
            sender_playback_output_channels=sender_playback_output_channels,
            sender_playback_hardware_channels=sender_playback_hardware_channels,
            video_source=video_source,
            video_device=video_device,
            sender_audio_delay_ms=sender_audio_delay_ms,
            receiver_audio_transport=receiver_audio_transport,
            receiver_playback_device=receiver_playback_device,
            receiver_video_output=receiver_video_output,
            receiver_video_delay_ms=receiver_video_delay_ms,
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
        runtime_dir: Path,
        log_capacity: int = 500,
    ) -> None:
        self._python_executable = python_executable
        self._project_root = project_root
        self._config_path = config_path
        self._recording_dir = recording_dir
        self._archive_dir = archive_dir
        self._preview_dir = preview_dir
        self._runtime_dir = runtime_dir
        self._log_capacity = log_capacity

        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._server_runtime: ServerRuntime | None = None
        self._current_request: RuntimeLaunchRequest | None = None
        self._active_process_request: RuntimeLaunchRequest | None = None
        self._log_lines: deque[str] = deque(maxlen=log_capacity)
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_exit_code: int | None = None
        self._sender_recovery = SenderRecoveryPolicy()
        self._ignored_process_pids: set[int] = set()
        self._sender_retry_timer: threading.Timer | None = None
        self._sender_stable_timer: threading.Timer | None = None
        self._sender_health_timer: threading.Timer | None = None
        self._last_sender_health_warning_at: float | None = None

    def start(self, request: RuntimeLaunchRequest) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self._log_lines.clear()
            self._sender_recovery.reset()
            self._last_sender_health_warning_at = None
            self._cancel_sender_timers_locked()

        if request.role == "server":
            runtime = ServerRuntime(
                config_path=self._config_path,
                recording_dir=self._recording_dir,
                archive_dir=self._archive_dir,
                preview_dir=self._preview_dir,
                log_callback=self.record_event,
            )
            with self._lock:
                self._server_runtime = runtime
                self._current_request = request
                self._active_process_request = None
                self._started_at = time.time()
                self._stopped_at = None
                self._last_exit_code = None
            try:
                runtime.start()
            except Exception:
                with self._lock:
                    if self._server_runtime is runtime:
                        self._last_exit_code = 1
                        self._stopped_at = time.time()
                raise
            with self._lock:
                if self._server_runtime is runtime:
                    self._started_at = time.time()
                    self._stopped_at = None
                    self._last_exit_code = None
        else:
            active_request = self._prepare_process_request(request)
            process = self._launch_process(active_request)
            start_watchers = False
            with self._lock:
                self._process = process
                self._current_request = request
                self._active_process_request = active_request
                self._started_at = time.time()
                self._stopped_at = None
                self._last_exit_code = None
                start_watchers = True
                if request.role == "sender":
                    self._sender_recovery.launched(active_request, self._started_at)
                    self._schedule_sender_timers_locked()
            if start_watchers:
                self._start_process_watchers(process)

        self.record_event(f"{request.role.title()} role started.")
        return self.snapshot()

    def stop(self, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            self._cancel_sender_timers_locked()
            self._last_sender_health_warning_at = None
            self._sender_recovery.reset()
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
                    self._active_process_request = None
                    self._stopped_at = time.time()
                    self._last_exit_code = runtime.snapshot().get("last_exit_code", 0)
            return self.snapshot()

        assert process is not None
        self.record_event(f"Stopping {self._current_request.role if self._current_request else 'process'} role...")
        with self._lock:
            self._ignored_process_pids.add(process.pid)
        exit_code = self._terminate_process(process, timeout=timeout)
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

    def set_sync_delay(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Sync delay payload must be a JSON object.")

        with self._lock:
            self._sync_state_locked()
            request = self._current_request
            active_request = self._active_process_request
            process = self._process

        if process is None or request is None or request.role not in {"sender", "receiver"}:
            raise RuntimeError("Sync delay controls require a running sender or receiver role.")

        if request.role == "sender":
            if (
                active_request is None
                or not active_request.audio_enabled
                or active_request.sender_audio_mode != "aec"
            ):
                raise RuntimeError("Sender audio delay requires active Playback + DSP mode; the sender is currently degraded.")
            delay_ms = _parse_sync_delay_ms(
                payload.get("sender_audio_delay_ms", payload.get("delay_ms", request.sender_audio_delay_ms)),
                "sender_audio_delay_ms",
            )
            next_request = replace(request, sender_audio_delay_ms=delay_ms)
            self._write_sync_delay_file("sender-audio-delay-ms.txt", delay_ms)
            label = "sender audio playback/probe"
        else:
            delay_ms = _parse_sync_delay_ms(
                payload.get("receiver_video_delay_ms", payload.get("delay_ms", request.receiver_video_delay_ms)),
                "receiver_video_delay_ms",
            )
            next_request = replace(request, receiver_video_delay_ms=delay_ms)
            self._write_sync_delay_file("receiver-video-delay-ms.txt", delay_ms)
            label = "receiver video"

        with self._lock:
            if self._current_request is request:
                self._current_request = next_request
        self.record_event(f"Updated {label} delay to {delay_ms} ms.")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._sync_state_locked()
            request = self._current_request
            server = self._server_runtime.snapshot() if self._server_runtime is not None else None
            sender = self._build_sender_snapshot_locked(request)
            receiver = self._build_receiver_snapshot_locked(request)
            running = self._process is not None or (server is not None and server.get("running"))
            active_request = self._active_process_request
            return {
                "running": running,
                "role": request.role if request is not None else None,
                "launch": request.to_dict() if request is not None else None,
                "active_launch": active_request.to_dict() if active_request is not None else None,
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

    def _prepare_process_request(self, request: RuntimeLaunchRequest) -> RuntimeLaunchRequest:
        if request.role != "sender":
            self._write_initial_sync_delay(request)
            return request

        now = time.time()
        self.record_event("Sender requested: " + _sender_request_summary(request, self._read_config_for_preflight()))
        preflight_errors = self._sender_preflight_errors(request)
        if preflight_errors:
            self.record_event("Sender preflight errors: " + _format_error_list(preflight_errors))
        else:
            self.record_event(
                "Sender preflight passed for "
                f"{_sender_mode_label(sender_mode_for_request(request))}; starting requested mode."
            )
        capture_errors = _sender_preflight_errors_for(preflight_errors, "capture")
        playback_errors = _sender_preflight_errors_for(preflight_errors, "playback")
        if capture_errors:
            self.record_event("Sender capture preflight classification: " + _format_error_list(capture_errors))
        if playback_errors:
            self.record_event("Sender playback preflight classification: " + _format_error_list(playback_errors))
        if capture_errors and request.audio_source == "device":
            fallback = video_only_request(request)
            active_request = self._sender_recovery.begin_degraded(
                request,
                fallback,
                now,
                "Sender capture preflight failed: " + "; ".join(capture_errors),
            )
            self._write_initial_sync_delay(active_request)
            retry_note = (
                " while retrying in the background"
                if sender_mode_for_request(request) == PLAYBACK_DSP_MODE
                else ""
            )
            self.record_event(
                f"Sender capture preflight failed; starting video-only{retry_note}. "
                + " ".join(capture_errors)
            )
            self.record_event("Sender fallback selected: " + _sender_request_summary(active_request, self._read_config_for_preflight()))
            return active_request

        active_request = self._sender_recovery.begin(request, now, preflight_errors)
        self._write_initial_sync_delay(active_request)
        if active_request is not request:
            self.record_event(
                "Playback + DSP preflight failed; starting sender in "
                f"{_sender_mode_label(sender_mode_for_request(active_request))} while retrying in the background. "
                + " ".join(preflight_errors)
            )
            self.record_event("Sender fallback selected: " + _sender_request_summary(active_request, self._read_config_for_preflight()))
        return active_request

    def _launch_process(self, request: RuntimeLaunchRequest) -> subprocess.Popen[str]:
        command, working_dir = self._build_process_command(request)
        if request.role == "sender":
            self.record_event(
                "Launching sender "
                f"{_sender_mode_label(sender_mode_for_request(request))}: "
                f"{_format_command_for_log(command)}"
            )
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["CONFIG_PATH"] = str(self._config_path)
        process = subprocess.Popen(
            command,
            cwd=working_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        return process

    def _start_process_watchers(self, process: subprocess.Popen[str]) -> None:
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

    def _build_process_command(self, request: RuntimeLaunchRequest) -> tuple[list[str], Path]:
        if request.role == "sender":
            self._preview_dir.mkdir(parents=True, exist_ok=True)
            preview_pattern = build_sender_preview_pattern(self._preview_dir, request.country or "tn")
            prune_preview_files(self._preview_dir, preview_pattern, keep=0)
            command = [self._python_executable, "send.py", "--country", request.country or "tn", "--supervised"]
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
            if request.audio_enabled and request.sender_audio_rate:
                command.extend(["--audio-rate", str(request.sender_audio_rate)])
            if request.audio_source == "device":
                command.extend(
                    [
                        "--capture-input-channels",
                        _format_channel_pair(request.sender_capture_input_channels),
                        "--capture-hardware-channels",
                        str(request.sender_capture_hardware_channels),
                    ]
                )
            if request.sender_audio_mode == "aec" and request.sender_playback_device:
                command.extend(["--playback-device", request.sender_playback_device])
            if request.sender_audio_mode == "aec" and request.audio_enabled:
                command.extend(
                    [
                        "--playback-output-channels",
                        _format_channel_pair(request.sender_playback_output_channels),
                        "--playback-hardware-channels",
                        str(request.sender_playback_hardware_channels),
                    ]
                )
            if request.sender_audio_mode == "aec" and request.audio_enabled:
                command.extend(
                    [
                        "--audio-delay-ms",
                        str(request.sender_audio_delay_ms),
                        "--sync-delay-file",
                        str(self._sync_delay_file("sender-audio-delay-ms.txt")),
                    ]
                )
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
                "--video-delay-ms",
                str(request.receiver_video_delay_ms),
                "--sync-delay-file",
                str(self._sync_delay_file("receiver-video-delay-ms.txt")),
                "--preview-pattern",
                preview_pattern,
            ]
            if request.receiver_playback_device:
                command.extend(["--playback-device", request.receiver_playback_device])
            if request.receiver_video_output:
                command.extend(["--video-output", request.receiver_video_output])
            working_dir = self._project_root / "production" / "3_receiver"
            return command, working_dir

        raise ValueError(f"Unsupported subprocess role: {request.role}")

    def _write_initial_sync_delay(self, request: RuntimeLaunchRequest) -> None:
        if request.role == "sender":
            self._write_sync_delay_file("sender-audio-delay-ms.txt", request.sender_audio_delay_ms)
        elif request.role == "receiver":
            self._write_sync_delay_file("receiver-video-delay-ms.txt", request.receiver_video_delay_ms)

    def _sync_delay_file(self, filename: str) -> Path:
        return self._runtime_dir / filename

    def _write_sync_delay_file(self, filename: str, delay_ms: int) -> None:
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        self._sync_delay_file(filename).write_text(f"{delay_ms}\n", encoding="utf-8")

    def _build_sender_snapshot_locked(self, request: RuntimeLaunchRequest | None) -> dict[str, Any] | None:
        if request is None or request.role != "sender" or request.country is None:
            return None

        preview_pattern = build_sender_preview_pattern(self._preview_dir, request.country)
        return {
            "country": request.country,
            "preview": describe_latest_preview(self._preview_dir, preview_pattern),
            "recovery": self._sender_recovery.snapshot(time.time()),
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
        recovery_action = None
        ignored = False
        with self._lock:
            ignored = process.pid in self._ignored_process_pids
            if ignored:
                self._ignored_process_pids.discard(process.pid)
            if self._process is process:
                self._process = None
                self._last_exit_code = exit_code
                self._stopped_at = time.time()
                should_log = True
                if self._active_process_request is not None and self._active_process_request.role == "sender":
                    if ignored:
                        self._active_process_request = None
                    else:
                        recovery_action = self._sender_recovery.on_exit(exit_code, self._stopped_at)
                        self._active_process_request = None
            elif self._last_exit_code is None:
                self._last_exit_code = exit_code
                self._stopped_at = self._stopped_at or time.time()

        if should_log:
            self.record_event(f"Role process exited with code {exit_code}.")
        if recovery_action is not None:
            self._handle_sender_recovery_action(recovery_action)

    def _sync_state_locked(self) -> None:
        if self._process is not None:
            exit_code = self._process.poll()
            if (
                exit_code is not None
                and (
                    self._active_process_request is None
                    or self._active_process_request.role != "sender"
                )
            ):
                self._process = None
                self._last_exit_code = exit_code
                self._stopped_at = self._stopped_at or time.time()
                self._active_process_request = None

        if self._server_runtime is not None:
            server_snapshot = self._server_runtime.snapshot()
            if not server_snapshot.get("running"):
                self._last_exit_code = server_snapshot.get("last_exit_code")
                self._stopped_at = self._stopped_at or time.time()
                self._server_runtime = None
                self._active_process_request = None

    def _handle_sender_recovery_action(self, action: RecoveryAction) -> None:
        if action.reason:
            self.record_event(f"Sender recovery: {action.reason}")
        if action.kind != "launch" or action.request is None:
            with self._lock:
                self._cancel_sender_timers_locked()
            return

        self.record_event(
            "Sender recovery launching "
            f"{_sender_mode_label(sender_mode_for_request(action.request))} mode."
        )
        self._replace_active_process(action.request)

    def _replace_active_process(self, request: RuntimeLaunchRequest) -> None:
        with self._lock:
            old_process = self._process
            if old_process is not None:
                self._ignored_process_pids.add(old_process.pid)

        if old_process is not None:
            exit_code = self._terminate_process(old_process, timeout=10)
            self._record_exit(old_process, exit_code)

        self._write_initial_sync_delay(request)
        try:
            process = self._launch_process(request)
        except Exception as exc:
            self.record_event(f"Sender recovery could not launch {_sender_mode_label(sender_mode_for_request(request))}: {exc}")
            with self._lock:
                action = self._sender_recovery.on_exit(1, time.time())
            self._handle_sender_recovery_action(action)
            return

        now = time.time()
        with self._lock:
            self._process = process
            self._active_process_request = request
            self._stopped_at = None
            self._last_exit_code = None
            self._sender_recovery.launched(request, now)
            self._schedule_sender_timers_locked()
        self._start_process_watchers(process)

    def _terminate_process(self, process: subprocess.Popen[str], timeout: float = 10.0) -> int:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.record_event("Role process did not stop in time. Killing process.")
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return process.wait(timeout=5)

    def _cancel_sender_timers_locked(self) -> None:
        if self._sender_retry_timer is not None:
            self._sender_retry_timer.cancel()
            self._sender_retry_timer = None
        if self._sender_stable_timer is not None:
            self._sender_stable_timer.cancel()
            self._sender_stable_timer = None
        if self._sender_health_timer is not None:
            self._sender_health_timer.cancel()
            self._sender_health_timer = None

    def _schedule_sender_timers_locked(self) -> None:
        self._cancel_sender_timers_locked()
        snapshot = self._sender_recovery.snapshot(time.time())
        if sender_mode_for_request(self._active_process_request) == PLAYBACK_DSP_MODE:
            timer = threading.Timer(SENDER_HEALTH_CHECK_INTERVAL_SECONDS, self._check_sender_health)
            timer.daemon = True
            self._sender_health_timer = timer
            timer.start()
        if snapshot["phase"] == DEGRADED_PHASE and snapshot["next_retry_at"] is not None:
            delay = max(0.1, snapshot["next_retry_at"] - time.time())
            timer = threading.Timer(delay, self._attempt_sender_restore)
            timer.daemon = True
            self._sender_retry_timer = timer
            timer.start()
        if snapshot["phase"] == RESTORING_PHASE and snapshot["stable_after"] is not None:
            delay = max(0.1, snapshot["stable_after"] - time.time())
            timer = threading.Timer(delay, self._mark_sender_restore_stable)
            timer.daemon = True
            self._sender_stable_timer = timer
            timer.start()

    def _attempt_sender_restore(self) -> None:
        now = time.time()
        with self._lock:
            if not self._sender_recovery.due_for_retry(now):
                return
            desired_request = self._sender_recovery.state.desired_request
            active_mode = self._sender_recovery.state.active_mode

        if desired_request is None:
            return

        skip_capture_open = active_mode == CAPTURE_ONLY_MODE
        self.record_event("Playback + DSP retry preflight requested: " + _sender_request_summary(desired_request, self._read_config_for_preflight()))
        if skip_capture_open:
            self.record_event(
                "Playback + DSP retry preflight: skipping capture open check because "
                "capture-only fallback is currently using the microphone."
            )
        preflight_errors = self._sender_preflight_errors(desired_request, skip_capture_open=skip_capture_open)
        if preflight_errors:
            capture_errors = _sender_preflight_errors_for(preflight_errors, "capture")
            playback_errors = _sender_preflight_errors_for(preflight_errors, "playback")
            if capture_errors:
                self.record_event("Playback + DSP retry capture classification: " + _format_error_list(capture_errors))
            if playback_errors:
                self.record_event("Playback + DSP retry playback classification: " + _format_error_list(playback_errors))
            reason = "Playback + DSP retry preflight still failing: " + "; ".join(preflight_errors)
            with self._lock:
                if not self._sender_recovery.due_for_retry(time.time()):
                    return
                self._sender_recovery.defer_retry(time.time(), reason)
                next_retry = self._sender_recovery.snapshot(time.time()).get("next_retry_in_seconds")
                self._schedule_sender_timers_locked()
            self.record_event(f"{reason} Next retry in {next_retry}s.")
            return

        with self._lock:
            restore_request = self._sender_recovery.prepare_restore_attempt(time.time())
        if restore_request is None:
            return

        self.record_event("Playback + DSP retry preflight passed; restoring requested DSP mode now.")
        self.record_event("Retrying Playback + DSP now; video may briefly reconnect.")
        self._replace_active_process(restore_request)

    def _mark_sender_restore_stable(self) -> None:
        with self._lock:
            if self._process is None:
                return
            marked = self._sender_recovery.mark_stable(time.time())
            self._schedule_sender_timers_locked()
        if marked:
            self.record_event("Playback + DSP has been stable for 30s; degraded mode cleared.")

    def _check_sender_health(self) -> None:
        with self._lock:
            process = self._process
            request = self._current_request
            active_request = self._active_process_request
            active_started_at = self._sender_recovery.state.active_started_at

        if (
            process is None
            or process.poll() is not None
            or request is None
            or request.role != "sender"
            or active_request is None
            or sender_mode_for_request(active_request) != PLAYBACK_DSP_MODE
            or request.country is None
        ):
            return

        preview_pattern = build_sender_preview_pattern(self._preview_dir, request.country)
        preview = describe_latest_preview(self._preview_dir, preview_pattern)
        now = time.time()
        uptime = max(0.0, now - active_started_at) if active_started_at is not None else 0.0
        unhealthy_reason = None
        if not preview.get("available"):
            if uptime >= SENDER_PREVIEW_STALE_SECONDS:
                unhealthy_reason = (
                    f"Playback + DSP has been online for {int(uptime)}s but has not produced sender preview frames."
                )
        else:
            age_seconds = int(preview.get("age_seconds") or 0)
            if age_seconds >= SENDER_PREVIEW_STALE_SECONDS:
                unhealthy_reason = (
                    f"Playback + DSP sender preview is stale for {age_seconds}s; falling back to capture-only."
                )

        if unhealthy_reason is None:
            with self._lock:
                if (
                    self._process is process
                    and sender_mode_for_request(self._active_process_request) == PLAYBACK_DSP_MODE
                ):
                    self._schedule_sender_timers_locked()
            return

        should_log_warning = False
        with self._lock:
            if (
                self._process is not process
                or sender_mode_for_request(self._active_process_request) != PLAYBACK_DSP_MODE
            ):
                return
            if (
                self._last_sender_health_warning_at is None
                or now - self._last_sender_health_warning_at >= SENDER_PREVIEW_STALE_SECONDS
            ):
                self._last_sender_health_warning_at = now
                should_log_warning = True
            self._schedule_sender_timers_locked()

        if should_log_warning:
            self.record_event(
                "Sender health warning: "
                + unhealthy_reason
                + " Keeping Playback + DSP active; preview freshness alone is not treated as a DSP failure."
            )

    def _sender_preflight_errors(self, request: RuntimeLaunchRequest, *, skip_capture_open: bool = False) -> list[str]:
        if request.role != "sender" or sender_mode_for_request(request) == VIDEO_ONLY_MODE:
            return []

        errors: list[str] = []
        elements = [
            "srtsink",
            "rtpL16pay",
        ]
        if sender_mode_for_request(request) == PLAYBACK_DSP_MODE:
            elements.extend(["alsasink", "srtsrc", "webrtcechoprobe", "rtpL16depay"])
        if _sender_routes_require_mix_matrix(request):
            elements.append("audiomixmatrix")
        if request.audio_source == "device":
            elements.append("alsasrc")
            if sender_mode_for_request(request) == PLAYBACK_DSP_MODE:
                elements.append("webrtcdsp")
        else:
            elements.append("audiotestsrc")
        for element in sorted(set(elements)):
            if not self._gst_element_available(element):
                errors.append(f"missing GStreamer element {element}")

        config = self._read_config_for_preflight()
        audio = config.get("audio", {}) if isinstance(config.get("audio"), dict) else {}
        local_rate = request.sender_audio_rate or _safe_int(audio.get("rate"), 48000)
        if request.audio_source == "device":
            capture_device = request.audio_device or str(audio.get("device", "default"))
            capture_error = self._alsa_device_error(["arecord", "-l"], capture_device, "capture")
            if capture_error:
                errors.append(capture_error)
            if not skip_capture_open:
                capture_open_error = self._gst_capture_open_error(request, capture_device, local_rate)
                if capture_open_error:
                    errors.append(capture_open_error)
        if sender_mode_for_request(request) == PLAYBACK_DSP_MODE:
            playback_device = request.sender_playback_device or str(audio.get("playback_device", "default"))
            playback_error = self._alsa_device_error(["aplay", "-l"], playback_device, "playback")
            if playback_error:
                errors.append(playback_error)
            playback_open_error = self._gst_playback_open_error(request, playback_device, local_rate)
            if playback_open_error:
                errors.append(playback_open_error)

        return errors

    def _gst_capture_open_error(
        self,
        request: RuntimeLaunchRequest,
        capture_device: str,
        local_rate: int,
    ) -> str | None:
        if shutil.which("gst-launch-1.0") is None:
            return "capture preflight failed: gst-launch-1.0 unavailable"
        device = alsa_runtime_device(capture_device)
        channels = request.sender_capture_hardware_channels
        command = [
            "gst-launch-1.0",
            "-q",
            "alsasrc",
            f"device={device}",
            "num-buffers=5",
            "!",
            "capsfilter",
            f"caps=audio/x-raw,channels={channels},rate={local_rate}",
            "!",
            "fakesink",
            "sync=false",
        ]
        return self._run_gst_preflight(command, "capture")

    def _gst_playback_open_error(
        self,
        request: RuntimeLaunchRequest,
        playback_device: str,
        local_rate: int,
    ) -> str | None:
        if shutil.which("gst-launch-1.0") is None:
            return "playback preflight failed: gst-launch-1.0 unavailable"
        device = alsa_runtime_device(playback_device)
        output_channels = request.sender_playback_hardware_channels
        mix = build_output_pair_mix_element(
            request.sender_playback_output_channels,
            request.sender_playback_hardware_channels,
        )
        command = [
            "gst-launch-1.0",
            "-q",
            "audiotestsrc",
            "wave=silence",
            "num-buffers=5",
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            "capsfilter",
            f"caps=audio/x-raw,channels=2,rate={local_rate}",
        ]
        if mix:
            command.append("!")
            command.extend(shlex.split(mix))
        command.extend(
            [
                "!",
                "capsfilter",
                f"caps=audio/x-raw,channels={output_channels},rate={local_rate}",
                "!",
                "alsasink",
                f"device={device}",
                "sync=false",
                "async=false",
            ]
        )
        return self._run_gst_preflight(command, "playback")

    def _run_gst_preflight(self, command: list[str], label: str) -> str | None:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
        except subprocess.TimeoutExpired:
            return (
                f"{label} preflight failed: GStreamer open check timed out "
                f"[command: {_format_command_for_log(command)}]"
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{label} preflight failed: {exc} [command: {_format_command_for_log(command)}]"
        if result.returncode == 0:
            return None
        detail = (result.stderr or result.stdout or "").strip()
        return (
            f"{label} preflight failed: "
            f"{detail or f'gst-launch exited with code {result.returncode}'} "
            f"[command: {_format_command_for_log(command)}]"
        )

    def _gst_element_available(self, element: str) -> bool:
        if shutil.which("gst-inspect-1.0") is None:
            return False
        try:
            result = subprocess.run(
                ["gst-inspect-1.0", element],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
            )
        except subprocess.SubprocessError:
            return False
        return result.returncode == 0

    def _alsa_device_error(self, command: list[str], device: str, label: str) -> str | None:
        executable = command[0]
        if shutil.which(executable) is None:
            return f"{executable} unavailable for {label} device preflight"
        normalized_device = (device or "default").strip()
        if not normalized_device or normalized_device == "default":
            return None
        if not normalized_device.startswith("hw:"):
            return None
        try:
            card, alsa_device = normalized_device.removeprefix("hw:").split(",", 1)
        except ValueError:
            return f"{label} device {normalized_device!r} is not a valid hw:CARD,DEVICE ALSA name"
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except subprocess.SubprocessError as exc:
            return f"could not list {label} devices with {executable}: {exc}"
        if result.returncode != 0:
            return f"could not list {label} devices with {executable}: {result.stderr.strip() or result.stdout.strip()}"
        needle = f"card {card}:"
        device_needle = f"device {alsa_device}:"
        for line in result.stdout.splitlines():
            if needle in line and device_needle in line:
                return None
        return f"{label} device {normalized_device} is not visible to ALSA"

    def _read_config_for_preflight(self) -> dict[str, Any]:
        try:
            with self._config_path.open("r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except OSError:
            return {}
        return data if isinstance(data, dict) else {}


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_sync_delay_ms(value: Any, field_name: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer from 0 to {MAX_SYNC_DELAY_MS}.")
    try:
        delay_ms = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer from 0 to {MAX_SYNC_DELAY_MS}.") from exc
    if delay_ms < 0 or delay_ms > MAX_SYNC_DELAY_MS:
        raise ValueError(f"{field_name} must be between 0 and {MAX_SYNC_DELAY_MS} ms.")
    return delay_ms


def _parse_optional_audio_rate(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return validate_local_audio_rate(value)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _parse_channel_pair(value: Any, field_name: str) -> tuple[int, int]:
    try:
        pair = normalize_audio_channel_pair(value, field_name)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return (pair[0], pair[1])


def _parse_hardware_channels(value: Any, pair: tuple[int, int], field_name: str) -> int:
    try:
        return normalize_audio_hardware_channels(value, list(pair), field_name)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _format_error_list(errors: list[str]) -> str:
    return " | ".join(errors) if errors else "none"


def _sender_request_summary(request: RuntimeLaunchRequest, config: dict[str, Any] | None = None) -> str:
    audio = config.get("audio", {}) if isinstance(config, dict) and isinstance(config.get("audio"), dict) else {}
    mode = sender_mode_for_request(request)
    fields = [
        f"mode={_sender_mode_label(mode)}",
        f"country={request.country or 'default'}",
        f"video_source={request.video_source}",
        f"audio_source={request.audio_source}",
    ]
    if request.video_device:
        fields.append(f"video_device={request.video_device}")
    if request.audio_enabled:
        local_rate = request.sender_audio_rate or _safe_int(audio.get("rate"), 48000)
        fields.append(f"audio_rate={local_rate}")
        if request.audio_source == "device":
            capture_device = request.audio_device or str(audio.get("device", "default"))
            fields.extend(
                [
                    f"capture_device={capture_device}",
                    f"capture_runtime_device={alsa_runtime_device(capture_device)}",
                    f"capture_pair={_format_channel_pair(request.sender_capture_input_channels)}",
                    f"capture_hardware_channels={request.sender_capture_hardware_channels}",
                ]
            )
        if request.sender_audio_mode == "aec":
            playback_device = request.sender_playback_device or str(audio.get("playback_device", "default"))
            fields.extend(
                [
                    f"playback_device={playback_device}",
                    f"playback_runtime_device={alsa_runtime_device(playback_device)}",
                    f"playback_pair={_format_channel_pair(request.sender_playback_output_channels)}",
                    f"playback_hardware_channels={request.sender_playback_hardware_channels}",
                    f"audio_delay_ms={request.sender_audio_delay_ms}",
                ]
            )
    return "; ".join(fields)


def _format_channel_pair(pair: tuple[int, int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def _format_command_for_log(command: list[str]) -> str:
    # Keep GStreamer link markers visually unquoted in control logs; they are
    # direct argv tokens, not shell syntax, and quoting them in diagnostics made
    # the preflight command look different from the user-run gst-launch command.
    return " ".join("!" if token == "!" else shlex.quote(token) for token in command)


def _sender_routes_require_mix_matrix(request: RuntimeLaunchRequest) -> bool:
    if request.audio_source == "device" and (
        request.sender_capture_input_channels != (1, 2)
        or request.sender_capture_hardware_channels != 2
    ):
        return True
    if request.sender_audio_mode == "aec" and request.audio_enabled and (
        request.sender_playback_output_channels != (1, 2)
        or request.sender_playback_hardware_channels != 2
    ):
        return True
    return False


def _sender_mode_label(mode: str | None) -> str:
    if mode == PLAYBACK_DSP_MODE:
        return "Playback + DSP"
    if mode == CAPTURE_ONLY_MODE:
        return "capture-only"
    if mode == VIDEO_ONLY_MODE:
        return "video-only"
    return mode or "unknown"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sender_preflight_errors_for(errors: list[str], prefix: str) -> list[str]:
    normalized_prefix = prefix.strip().lower()
    return [
        error
        for error in errors
        if error.lower().startswith(f"{normalized_prefix} preflight failed")
        or error.lower().startswith(f"{normalized_prefix} device")
    ]
