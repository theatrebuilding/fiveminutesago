from __future__ import annotations

from collections import deque
import datetime as dt
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any


class RelaySupervisor:
    def __init__(
        self,
        python_executable: str,
        working_dir: Path,
        log_capacity: int = 500,
    ) -> None:
        self._python_executable = python_executable
        self._working_dir = working_dir
        self._log_capacity = log_capacity

        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._log_lines: deque[str] = deque(maxlen=log_capacity)
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_exit_code: int | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._sync_process_state_locked()
            if self._process is not None:
                return self._snapshot_locked()

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                [self._python_executable, "server.py"],
                cwd=self._working_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._process = process
            self._started_at = time.time()
            self._stopped_at = None
            self._last_exit_code = None

        self.record_event("Relay process started.")
        threading.Thread(
            target=self._drain_output,
            args=(process,),
            daemon=True,
            name="relay-log-reader",
        ).start()
        threading.Thread(
            target=self._watch_process,
            args=(process,),
            daemon=True,
            name="relay-process-watcher",
        ).start()
        return self.snapshot()

    def stop(self, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            self._sync_process_state_locked()
            process = self._process
            if process is None:
                return self._snapshot_locked()

        self.record_event("Stopping relay process...")
        process.terminate()

        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.record_event("Relay did not stop in time. Killing process.")
            process.kill()
            exit_code = process.wait(timeout=5)

        self._record_exit(process, exit_code)
        return self.snapshot()

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def restart_or_start(self) -> dict[str, Any]:
        if self.snapshot()["running"]:
            return self.restart()
        return self.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._sync_process_state_locked()
            return self._snapshot_locked()

    def record_event(self, message: str) -> None:
        timestamp = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        with self._lock:
            self._log_lines.append(f"[control {timestamp}] {message}")

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
            self.record_event(f"Relay process exited with code {exit_code}.")

    def _sync_process_state_locked(self) -> None:
        if self._process is None:
            return

        exit_code = self._process.poll()
        if exit_code is None:
            return

        self._process = None
        self._last_exit_code = exit_code
        self._stopped_at = self._stopped_at or time.time()

    def _snapshot_locked(self) -> dict[str, Any]:
        running = self._process is not None
        started_at_iso = _to_iso(self._started_at)
        stopped_at_iso = _to_iso(self._stopped_at)
        uptime_seconds = int(time.time() - self._started_at) if running and self._started_at else None

        return {
            "running": running,
            "pid": self._process.pid if running else None,
            "started_at": started_at_iso,
            "started_at_ts": self._started_at,
            "stopped_at": stopped_at_iso,
            "stopped_at_ts": self._stopped_at,
            "uptime_seconds": uptime_seconds,
            "last_exit_code": self._last_exit_code,
            "working_dir": str(self._working_dir),
            "python_executable": self._python_executable,
            "log_tail": list(self._log_lines),
        }


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
