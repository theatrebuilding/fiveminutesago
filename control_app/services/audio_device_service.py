from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from production.audio_support import COMMON_AUDIO_HARDWARE_RATES, channel_pairs_for_count


ALSA_CARD_PATTERN = re.compile(
    r"^card\s+(?P<card>\d+):\s+(?P<card_id>[^\s]+)\s+\[(?P<card_name>.+?)\],\s+device\s+(?P<device>\d+):\s+(?P<device_name>.+?)\s+\[(?P<device_label>.+?)\]$"
)
ALSA_HW_PATTERN = re.compile(r"^hw:(?P<card>\d+),(?P<device>\d+)$")
COMMON_AUDIO_RATES = COMMON_AUDIO_HARDWARE_RATES


class AudioDeviceService:
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
            "direction": direction,
            "rates": sorted(rates),
            "supported_rates": supported_rates,
            "channel_counts": sorted(channel_counts),
            "max_channels": max_channels,
            "pairs": channel_pairs_for_count(max_channels),
            "warnings": warnings,
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
