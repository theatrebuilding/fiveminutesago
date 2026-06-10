from __future__ import annotations

import math
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from production.audio_support import (
    COMMON_AUDIO_HARDWARE_RATES,
    alsa_runtime_device,
    build_gst_audio_raw_caps,
    build_input_pair_mix_element,
    build_output_pair_mix_element,
    channel_pairs_for_count,
    format_gst_mix_matrix,
    normalize_audio_channel_pair,
    resolve_audio_hardware_channels,
)


ALSA_CARD_PATTERN = re.compile(
    r"^card\s+(?P<card>\d+):\s+(?P<card_id>[^\s]+)\s+\[(?P<card_name>.+?)\],\s+device\s+(?P<device>\d+):\s+(?P<device_name>.+?)\s+\[(?P<device_label>.+?)\]$"
)
ALSA_HW_PATTERN = re.compile(r"^hw:(?P<card>\d+),(?P<device>\d+)$")
COMMON_AUDIO_RATES = COMMON_AUDIO_HARDWARE_RATES
SPEAKER_TEST_CHANNEL_SECONDS = 2.0
SPEAKER_TEST_SHUTDOWN_SECONDS = 1.0
SPEAKER_TEST_CHANNEL_GAP_SECONDS = 0.15
DEFAULT_TEST_AUDIO_RATE = 48000


class AudioDeviceService:
    def __init__(self) -> None:
        self._level_tests: dict[str, dict[str, Any]] = {}
        self._level_tests_lock = threading.Lock()

    def list_devices(self) -> list[dict[str, Any]]:
        return self.list_capture_devices()

    def list_capture_devices(self) -> list[dict[str, Any]]:
        return self._list_alsa_devices(["arecord", "-l"])

    def list_playback_devices(self) -> list[dict[str, Any]]:
        return self._list_alsa_devices(["aplay", "-l"])

    def capture_device_details(self, device: str | None) -> dict[str, Any]:
        return self._device_details(device, "capture")

    def playback_device_details(self, device: str | None) -> dict[str, Any]:
        return self._device_details(device, "playback")

    def _device_details(self, device: str | None, direction: str) -> dict[str, Any]:
        normalized_device = (device or "default").strip() or "default"
        warnings: list[str] = []
        rates: set[int] = set()
        channel_counts: set[int] = set()

        match = ALSA_HW_PATTERN.match(normalized_device)
        if match is None:
            warnings.append(
                "Detailed probing is available for hw:CARD,DEVICE ALSA names. "
                "Using safe stereo defaults for this device string."
            )
        else:
            proc_details = self._proc_asound_details(match.group("card"), direction)
            rates.update(proc_details["rates"])
            channel_counts.update(proc_details["channel_counts"])
            warnings.extend(proc_details["warnings"])

        if channel_counts:
            max_channels = max(channel_counts)
        elif match is not None:
            max_channels = 12
            warnings.append(
                "Could not detect hardware channel count; showing fallback channel pairs up to 11/12."
            )
        else:
            max_channels = 2
        supported_rates = sorted(rates) if rates else list(COMMON_AUDIO_HARDWARE_RATES)
        if rates:
            if 48000 not in rates:
                warnings.append("This device did not report 48000 Hz.")
        else:
            warnings.append("Could not detect hardware rates; showing common hardware rates.")

        return {
            "device": normalized_device,
            "runtime_device": alsa_runtime_device(normalized_device),
            "direction": direction,
            "rates": sorted(rates),
            "supported_rates": supported_rates,
            "channel_counts": sorted(channel_counts),
            "max_channels": max_channels,
            "pairs": channel_pairs_for_count(max_channels, sorted(channel_counts)),
            "warnings": warnings,
        }

    def run_playback_test(self, settings: dict[str, Any]) -> dict[str, Any]:
        commands = self.build_speaker_test_commands(settings)
        if not commands:
            raise ValueError("No playback channels were selected.")

        outputs: list[str] = []
        for command in commands:
            output = self._run_bounded_gst_test(command)
            if output:
                outputs.append(output)
            time.sleep(SPEAKER_TEST_CHANNEL_GAP_SECONDS)

        return {
            "ok": True,
            "message": "Output test completed.",
            "commands": commands,
            "output": "\n".join(outputs),
        }

    def _run_bounded_gst_test(self, command: list[str]) -> str:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("gst-launch-1.0 is not available in this container.") from exc

        try:
            stdout, stderr = process.communicate(timeout=SPEAKER_TEST_CHANNEL_SECONDS)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=SPEAKER_TEST_SHUTDOWN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            output = "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part)
            if process.returncode and process.returncode > 0:
                raise RuntimeError(output or f"gst-launch-1.0 exited with code {process.returncode}.")
            return output

        output = "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part)
        if process.returncode != 0:
            raise RuntimeError(output or f"gst-launch-1.0 exited with code {process.returncode}.")
        return output

    def build_speaker_test_commands(self, settings: dict[str, Any]) -> list[list[str]]:
        pair = normalize_audio_channel_pair(settings.get("output_channels", [1, 2]), "output_channels")
        hardware_channels = resolve_audio_hardware_channels(
            settings.get("hardware_channels"),
            pair,
            settings.get("supported_channel_counts"),
            "hardware_channels",
        )
        device = alsa_runtime_device(settings.get("device", "default"))
        audio_rate = _test_audio_rate(settings)
        output_mix = build_output_pair_mix_element(pair, hardware_channels)
        commands: list[list[str]] = []
        for side in ("left", "right"):
            command = [
                "gst-launch-1.0",
                "-q",
                "audiotestsrc",
                "is-live=true",
                "wave=sine",
                "freq=880",
                "volume=0.2",
                "!",
                "audioconvert",
                "!",
                "capsfilter",
                f"caps={build_gst_audio_raw_caps(audio_format='S16LE', channels=2, rate=audio_rate)}",
                "!",
            ]
            command.extend(shlex.split(_stereo_side_matrix_element(side)))
            command.extend(
                [
                    "!",
                    "capsfilter",
                    f"caps={build_gst_audio_raw_caps(audio_format='S16LE', channels=2, rate=audio_rate)}",
                ]
            )
            if output_mix:
                command.append("!")
                command.extend(shlex.split(output_mix))
            command.extend(
                [
                    "!",
                    "capsfilter",
                    f"caps={build_gst_audio_raw_caps(audio_format='S16LE', channels=hardware_channels, rate=audio_rate)}",
                    "!",
                    "alsasink",
                    f"device={device}",
                    "sync=false",
                    "async=false",
                ]
            )
            commands.append(command)
        return commands

    def start_capture_level_test(self, settings: dict[str, Any]) -> dict[str, Any]:
        self._cleanup_level_tests()
        command, metadata = self.build_capture_level_command(settings)
        test_id = uuid.uuid4().hex
        now = time.time()
        session = {
            "id": test_id,
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "duration_seconds": metadata["duration_seconds"],
            "command": command,
            "device": metadata["device"],
            "runtime_device": metadata["runtime_device"],
            "rate": metadata.get("rate"),
            "hardware_channels": metadata["hardware_channels"],
            "input_channels": metadata["input_channels"],
            "levels": {
                "left": {"peak": 0.0, "rms": 0.0},
                "right": {"peak": 0.0, "rms": 0.0},
            },
            "error": None,
        }
        with self._level_tests_lock:
            self._level_tests[test_id] = session
        thread = threading.Thread(
            target=self._run_capture_level_test,
            args=(test_id, command, metadata),
            daemon=True,
            name=f"audio-level-test-{test_id[:8]}",
        )
        thread.start()
        return self.get_capture_level_test(test_id)

    def get_capture_level_test(self, test_id: str) -> dict[str, Any]:
        with self._level_tests_lock:
            session = self._level_tests.get(test_id)
            if session is None:
                raise KeyError(test_id)
            return _public_level_test_snapshot(dict(session))

    def build_capture_level_command(self, settings: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        pair = normalize_audio_channel_pair(settings.get("input_channels", [1, 2]), "input_channels")
        supported_counts = settings.get("supported_channel_counts")
        hardware_channels = resolve_audio_hardware_channels(
            settings.get("hardware_channels"),
            pair,
            supported_counts,
            "hardware_channels",
        )
        duration_seconds = int(settings.get("duration_seconds") or 10)
        duration_seconds = max(1, min(duration_seconds, 10))
        source_device = str(settings.get("device") or "default").strip() or "default"
        runtime_device = alsa_runtime_device(source_device)
        audio_rate = _test_audio_rate(settings)
        capture_mix = build_input_pair_mix_element(pair, hardware_channels)
        command = [
            "gst-launch-1.0",
            "-q",
            "alsasrc",
            f"device={runtime_device}",
            "do-timestamp=true",
            "!",
            "capsfilter",
            f"caps={build_gst_audio_raw_caps(audio_format='S16LE', channels=hardware_channels, rate=audio_rate)}",
        ]
        if capture_mix:
            command.append("!")
            command.extend(shlex.split(capture_mix))
        command.extend(
            [
                "!",
                "capsfilter",
                f"caps={build_gst_audio_raw_caps(audio_format='S16LE', channels=2, rate=audio_rate)}",
                "!",
                "fdsink",
                "fd=1",
                "sync=false",
            ]
        )
        return command, {
            "device": source_device,
            "runtime_device": runtime_device,
            "rate": audio_rate,
            "hardware_channels": hardware_channels,
            "input_channels": pair,
            "analysis_channels": 2,
            "analysis_input_channels": [1, 2],
            "duration_seconds": duration_seconds,
        }

    def _list_alsa_devices(self, command: list[str]) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []

        if result.returncode != 0:
            return []

        devices: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            match = ALSA_CARD_PATTERN.match(line.strip())
            if match is None:
                continue

            card = match.group("card")
            device = match.group("device")
            pcm_id = f"hw:{card},{device}"
            devices.append(
                {
                    "id": pcm_id,
                    "path": pcm_id,
                    "label": f'{match.group("card_name")} / {match.group("device_label")}',
                    "card": int(card),
                    "device": int(device),
                    "card_id": match.group("card_id"),
                    "card_name": match.group("card_name"),
                    "device_name": match.group("device_name"),
                    "device_label": match.group("device_label"),
                }
            )

        return devices

    def _run_capture_level_test(self, test_id: str, command: list[str], metadata: dict[str, Any]) -> None:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            analysis_channels = int(metadata.get("analysis_channels") or metadata["hardware_channels"])
            analysis_input_channels = metadata.get("analysis_input_channels") or metadata["input_channels"]
            frame_bytes = analysis_channels * 2
            chunk_size = frame_bytes * 512
            assert process.stdout is not None
            deadline = time.time() + float(metadata["duration_seconds"])
            while time.time() < deadline:
                chunk = process.stdout.read(chunk_size)
                if not chunk:
                    break
                levels = _pcm_s16le_pair_levels(
                    chunk,
                    analysis_channels,
                    analysis_input_channels,
                )
                with self._level_tests_lock:
                    session = self._level_tests.get(test_id)
                    if session is None:
                        return
                    session["levels"] = levels
                    session["updated_at"] = time.time()
            terminated = False
            if process.poll() is None:
                process.terminate()
                terminated = True
            stdout, stderr = process.communicate(timeout=1)
            exit_code = process.returncode
            with self._level_tests_lock:
                session = self._level_tests.get(test_id)
                if session is None:
                    return
                session["updated_at"] = time.time()
                if terminated or exit_code == 0:
                    session["status"] = "completed"
                else:
                    session["status"] = "error"
                    session["error"] = stderr.decode("utf-8", errors="replace").strip() or f"gst-launch-1.0 exited with code {exit_code}."
        except FileNotFoundError:
            self._finish_level_test_with_error(test_id, "gst-launch-1.0 is not available in this container.")
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
            self._finish_level_test_with_error(test_id, "mic test pipeline did not shut down cleanly.")
        except Exception as exc:
            self._finish_level_test_with_error(test_id, str(exc))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()

    def _finish_level_test_with_error(self, test_id: str, message: str) -> None:
        with self._level_tests_lock:
            session = self._level_tests.get(test_id)
            if session is None:
                return
            session["status"] = "error"
            session["error"] = message
            session["updated_at"] = time.time()

    def _cleanup_level_tests(self) -> None:
        cutoff = time.time() - 60
        with self._level_tests_lock:
            stale_ids = [
                test_id
                for test_id, session in self._level_tests.items()
                if session.get("status") != "running" and float(session.get("updated_at") or 0) < cutoff
            ]
            for test_id in stale_ids:
                self._level_tests.pop(test_id, None)

    def _proc_asound_details(self, card: str, direction: str) -> dict[str, Any]:
        section_name = "Playback" if direction == "playback" else "Capture"
        rates: set[int] = set()
        channel_counts: set[int] = set()
        warnings: list[str] = []
        stream_paths = sorted(Path(f"/proc/asound/card{card}").glob("stream*"))
        if not stream_paths:
            warnings.append(f"No /proc/asound/card{card}/stream* details were visible.")
        for stream_path in stream_paths:
            try:
                parsed = self._parse_proc_stream_text(stream_path.read_text(encoding="utf-8"), section_name)
            except OSError as exc:
                warnings.append(f"Could not read {stream_path}: {exc}")
                continue
            rates.update(parsed["rates"])
            channel_counts.update(parsed["channel_counts"])
        return {
            "rates": rates,
            "channel_counts": channel_counts,
            "warnings": warnings,
        }

    @staticmethod
    def _parse_proc_stream_text(text: str, section_name: str) -> dict[str, set[int]]:
        active = False
        rates: set[int] = set()
        channel_counts: set[int] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line == f"{section_name}:":
                active = True
                continue
            if line in {"Playback:", "Capture:"} and line != f"{section_name}:":
                active = False
                continue
            if not active:
                continue
            if line.startswith("Rates:"):
                rates.update(_parse_numeric_field(line.removeprefix("Rates:").strip(), COMMON_AUDIO_RATES))
            elif line.startswith("Channels:"):
                channel_counts.update(_parse_numeric_field(line.removeprefix("Channels:").strip(), range(1, 65)))
        return {
            "rates": rates,
            "channel_counts": channel_counts,
        }


def _parse_numeric_field(value: str, common_values: Any) -> set[int]:
    values: set[int] = set()
    for part in re.split(r",\s*", value):
        cleaned = part.strip()
        if not cleaned:
            continue
        range_match = re.match(r"^(?P<start>\d+)\s*-\s*(?P<end>\d+)$", cleaned)
        if range_match:
            start = int(range_match.group("start"))
            end = int(range_match.group("end"))
            values.update(int(candidate) for candidate in common_values if start <= int(candidate) <= end)
            continue
        number_match = re.match(r"^\d+", cleaned)
        if number_match:
            values.add(int(number_match.group(0)))
    return values


def _test_audio_rate(settings: dict[str, Any]) -> int:
    explicit_rate = settings.get("rate")
    if explicit_rate not in {None, ""}:
        try:
            return int(explicit_rate)
        except (TypeError, ValueError):
            return DEFAULT_TEST_AUDIO_RATE

    try:
        from production.config_loader import load_config

        config = load_config()
    except BaseException:
        return DEFAULT_TEST_AUDIO_RATE
    audio = config.get("audio", {}) if isinstance(config, dict) and isinstance(config.get("audio"), dict) else {}
    try:
        return int(audio.get("rate", DEFAULT_TEST_AUDIO_RATE))
    except (TypeError, ValueError):
        return DEFAULT_TEST_AUDIO_RATE


def _stereo_side_matrix_element(side: str) -> str:
    if side == "right":
        rows = [[0.0, 0.0], [0.0, 1.0]]
    else:
        rows = [[1.0, 0.0], [0.0, 0.0]]
    return (
        'audiomixmatrix in-channels=2 out-channels=2 '
        f'channel-mask=-1 matrix="{format_gst_mix_matrix(rows)}"'
    )


def _pcm_s16le_pair_levels(
    chunk: bytes,
    hardware_channels: int,
    input_channels: list[int],
) -> dict[str, dict[str, float]]:
    frame_bytes = hardware_channels * 2
    frame_count = len(chunk) // frame_bytes
    if frame_count <= 0:
        return {
            "left": {"peak": 0.0, "rms": 0.0},
            "right": {"peak": 0.0, "rms": 0.0},
        }

    left_index = input_channels[0] - 1
    right_index = input_channels[1] - 1
    left_peak = 0
    right_peak = 0
    left_sum = 0.0
    right_sum = 0.0
    for frame in range(frame_count):
        frame_offset = frame * frame_bytes
        left = int.from_bytes(chunk[frame_offset + left_index * 2 : frame_offset + left_index * 2 + 2], "little", signed=True)
        right = int.from_bytes(chunk[frame_offset + right_index * 2 : frame_offset + right_index * 2 + 2], "little", signed=True)
        left_abs = abs(left)
        right_abs = abs(right)
        left_peak = max(left_peak, left_abs)
        right_peak = max(right_peak, right_abs)
        left_sum += left * left
        right_sum += right * right

    scale = 32768.0
    return {
        "left": {
            "peak": min(1.0, left_peak / scale),
            "rms": min(1.0, math.sqrt(left_sum / frame_count) / scale),
        },
        "right": {
            "peak": min(1.0, right_peak / scale),
            "rms": min(1.0, math.sqrt(right_sum / frame_count) / scale),
        },
    }


def _public_level_test_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    remaining = max(
        0.0,
        float(session.get("started_at") or now) + float(session.get("duration_seconds") or 0) - now,
    )
    return {
        "id": session["id"],
        "status": session["status"],
        "duration_seconds": session["duration_seconds"],
        "remaining_seconds": remaining if session["status"] == "running" else 0,
        "device": session.get("device"),
        "runtime_device": session.get("runtime_device"),
        "rate": session.get("rate"),
        "hardware_channels": session.get("hardware_channels"),
        "input_channels": session.get("input_channels"),
        "levels": session.get("levels"),
        "error": session.get("error"),
    }
