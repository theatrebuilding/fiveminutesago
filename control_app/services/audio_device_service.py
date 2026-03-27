from __future__ import annotations

import re
import subprocess
from typing import Any


CAPTURE_CARD_PATTERN = re.compile(
    r"^card\s+(?P<card>\d+):\s+(?P<card_id>[^\s]+)\s+\[(?P<card_name>.+?)\],\s+device\s+(?P<device>\d+):\s+(?P<device_name>.+?)\s+\[(?P<device_label>.+?)\]$"
)


class AudioDeviceService:
    def list_devices(self) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                ["arecord", "-l"],
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
            match = CAPTURE_CARD_PATTERN.match(line.strip())
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
                    "card_id": match.group("card_id"),
                    "card_name": match.group("card_name"),
                    "device_name": match.group("device_name"),
                    "device_label": match.group("device_label"),
                }
            )

        return devices
