from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import threading
import time
from typing import Callable


ACTIVE_PACKET_WINDOW_SECONDS = 3.0


@dataclass
class _MonitorState:
    label: str
    port: int
    available: bool = False
    process_running: bool = False
    packet_count: int = 0
    last_packet_at: float | None = None
    error: str | None = None


class UdpPacketMonitor:
    def __init__(
        self,
        ports: dict[str, int],
        log_callback: Callable[[str], None] | None = None,
        interface: str = "any",
    ) -> None:
        self._interface = interface
        self._log_callback = log_callback
        self._lock = threading.Lock()
        self._states = {
            label: _MonitorState(label=label, port=int(port))
            for label, port in ports.items()
        }
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._threads: list[threading.Thread] = []
        self._stopping = False

    def start(self) -> None:
        with self._lock:
            self._stopping = False

        if shutil.which("tcpdump") is None:
            with self._lock:
                for state in self._states.values():
                    state.error = "tcpdump unavailable"
            self._log("UDP packet monitor unavailable because tcpdump is not installed.")
            return

        for label, state in self._states.items():
            command = [
                "tcpdump",
                "-n",
                "-l",
                "-U",
                "-q",
                "-i",
                self._interface,
                "udp",
                "port",
                str(state.port),
            ]
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                with self._lock:
                    state.error = str(exc)
                self._log(f"[udp-{label}] Could not start tcpdump monitor. {exc}")
                continue

            with self._lock:
                state.available = True
                state.process_running = True
                state.error = None
                self._processes[label] = process

            stdout_thread = threading.Thread(
                target=self._watch_stdout,
                args=(label, process),
                name=f"udp-monitor-{label}-stdout",
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._watch_stderr,
                args=(label, process),
                name=f"udp-monitor-{label}-stderr",
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            self._threads.extend([stdout_thread, stderr_thread])

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stopping = True
            processes = list(self._processes.items())

        for label, process in processes:
            if process.poll() is None:
                process.terminate()

        deadline = time.time() + timeout
        for label, process in processes:
            remaining = max(0.1, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            finally:
                with self._lock:
                    state = self._states[label]
                    state.process_running = False
                    self._processes.pop(label, None)

        for thread in self._threads:
            thread.join(timeout=1)
        self._threads.clear()

    def snapshot(self) -> dict[str, dict[str, object]]:
        now = time.time()
        with self._lock:
            return {
                label: {
                    "port": state.port,
                    "available": state.available,
                    "process_running": state.process_running,
                    "packet_count": state.packet_count,
                    "last_packet_at": _to_iso(state.last_packet_at),
                    "last_packet_age_seconds": (
                        round(max(0.0, now - state.last_packet_at), 1)
                        if state.last_packet_at is not None
                        else None
                    ),
                    "receiving": (
                        state.last_packet_at is not None
                        and (now - state.last_packet_at) <= ACTIVE_PACKET_WINDOW_SECONDS
                    ),
                    "error": state.error,
                }
                for label, state in self._states.items()
            }

    def _watch_stdout(self, label: str, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        for line in process.stdout:
            cleaned = line.strip()
            if not cleaned:
                continue
            with self._lock:
                state = self._states[label]
                state.available = True
                state.process_running = process.poll() is None
                state.packet_count += 1
                state.last_packet_at = time.time()
                state.error = None

        with self._lock:
            state = self._states[label]
            state.process_running = False

    def _watch_stderr(self, label: str, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return

        for line in process.stderr:
            cleaned = line.strip()
            if not cleaned:
                continue
            if "listening on" in cleaned.lower():
                with self._lock:
                    state = self._states[label]
                    state.available = True
                    state.process_running = process.poll() is None
                continue
            if self._is_shutdown_noise(cleaned):
                continue
            with self._lock:
                state = self._states[label]
                state.error = cleaned
            self._log(f"[udp-{label}] {cleaned}")

        with self._lock:
            state = self._states[label]
            state.process_running = False

    def _is_shutdown_noise(self, message: str) -> bool:
        lowered = message.lower()
        if self._stopping and ("packets captured" in lowered or "packets received by filter" in lowered):
            return True
        return False

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    from .storage_service import _to_iso as storage_to_iso

    return storage_to_iso(timestamp)
