from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from control_app.services.audio_device_service import AudioDeviceService, _pcm_s16le_pair_levels


class AudioDeviceServiceTests(unittest.TestCase):
    def test_parse_proc_stream_text_extracts_section_rates_and_channels(self) -> None:
        text = """
Focusrite USB Audio
Playback:
  Interface 1
    Altset 1
    Format: S32_LE
    Channels: 10
    Rates: 44100, 48000, 88200, 96000
Capture:
  Interface 2
    Altset 1
    Format: S32_LE
    Channels: 12
    Rates: 44100, 48000
"""

        playback = AudioDeviceService._parse_proc_stream_text(text, "Playback")
        capture = AudioDeviceService._parse_proc_stream_text(text, "Capture")

        self.assertEqual(playback["channel_counts"], {10})
        self.assertEqual(playback["rates"], {44100, 48000, 88200, 96000})
        self.assertEqual(capture["channel_counts"], {12})
        self.assertEqual(capture["rates"], {44100, 48000})

    def test_parse_proc_stream_text_expands_ranges_to_common_values(self) -> None:
        parsed = AudioDeviceService._parse_proc_stream_text(
            "Playback:\n  Channels: 1 - 8\n  Rates: 8000 - 48000\n",
            "Playback",
        )

        self.assertEqual(parsed["channel_counts"], set(range(1, 9)))
        self.assertEqual(parsed["rates"], {8000, 16000, 32000, 44100, 48000})

    def test_speaker_test_commands_use_production_equivalent_playback_path(self) -> None:
        service = AudioDeviceService()

        commands = service.build_speaker_test_commands(
            {
                "device": "hw:2,0",
                "rate": 48000,
                "output_channels": [5, 6],
                "hardware_channels": 2,
                "supported_channel_counts": [10],
            }
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][:3], ["gst-launch-1.0", "-q", "audiotestsrc"])
        self.assertIn("audiomixmatrix", commands[0])
        self.assertIn("audiomixmatrix", commands[1])
        self.assertNotEqual(
            [arg for arg in commands[0] if arg.startswith("matrix=")][0],
            [arg for arg in commands[1] if arg.startswith("matrix=")][0],
        )
        self.assertIn("caps=audio/x-raw,format=S16LE,layout=interleaved,channels=2,rate=48000", commands[0])
        self.assertIn("in-channels=2", commands[0])
        self.assertIn("out-channels=10", commands[0])
        self.assertIn("channel-mask=0", commands[0])
        self.assertIn(
            "caps=audio/x-raw,format=S16LE,layout=interleaved,channels=10,rate=48000,channel-mask=(bitmask)0x0",
            commands[0],
        )
        self.assertIn("alsasink", commands[0])
        self.assertIn("device=plughw:2,0", commands[0])

    def test_playback_test_bounds_each_channel_and_continues_to_right(self) -> None:
        service = AudioDeviceService()
        started_commands: list[list[str]] = []
        processes: list[_TimeoutSpeakerProcess] = []

        def fake_popen(command: list[str], **_: object) -> "_TimeoutSpeakerProcess":
            started_commands.append(command)
            process = _TimeoutSpeakerProcess(command)
            processes.append(process)
            return process

        with patch("control_app.services.audio_device_service.subprocess.Popen", fake_popen), patch(
            "control_app.services.audio_device_service.time.sleep",
        ):
            result = service.run_playback_test(
                {
                    "device": "hw:2,0",
                    "rate": 48000,
                    "output_channels": [1, 2],
                    "hardware_channels": 2,
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(started_commands), 2)
        self.assertTrue(all(command[:3] == ["gst-launch-1.0", "-q", "audiotestsrc"] for command in started_commands))
        self.assertEqual([process.terminated for process in processes], [True, True])

    def test_playback_test_still_fails_fast_on_speaker_error(self) -> None:
        service = AudioDeviceService()

        with patch(
            "control_app.services.audio_device_service.subprocess.Popen",
            lambda command, **kwargs: _ExitedSpeakerProcess(command, 1, stderr="Playback open error"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Playback open error"):
                service.run_playback_test(
                    {
                        "device": "hw:2,0",
                        "rate": 48000,
                        "output_channels": [1, 2],
                        "hardware_channels": 2,
                    }
                )

    def test_capture_level_command_uses_production_equivalent_capture_path(self) -> None:
        service = AudioDeviceService()

        command, metadata = service.build_capture_level_command(
            {
                "device": "hw:2,0",
                "rate": 96000,
                "input_channels": [3, 4],
                "hardware_channels": 4,
                "supported_channel_counts": [2, 12],
                "duration_seconds": 99,
            }
        )

        self.assertEqual(command[:3], ["gst-launch-1.0", "-q", "alsasrc"])
        self.assertIn("device=plughw:2,0", command)
        self.assertIn(
            "caps=audio/x-raw,format=S16LE,layout=interleaved,channels=12,rate=96000,channel-mask=(bitmask)0x0",
            command,
        )
        self.assertIn("audiomixmatrix", command)
        self.assertIn("caps=audio/x-raw,format=S16LE,layout=interleaved,channels=2,rate=96000", command)
        self.assertIn("fdsink", command)
        self.assertEqual(metadata["input_channels"], [3, 4])
        self.assertEqual(metadata["analysis_channels"], 2)
        self.assertEqual(metadata["analysis_input_channels"], [1, 2])

    def test_pcm_s16le_pair_levels_reports_selected_input_pair(self) -> None:
        def sample(value: int) -> bytes:
            return int(value).to_bytes(2, "little", signed=True)

        # Two frames, four hardware channels. Only channels 3/4 should count.
        chunk = b"".join(
            [
                sample(0),
                sample(0),
                sample(16384),
                sample(-8192),
                sample(0),
                sample(0),
                sample(-32768),
                sample(4096),
            ]
        )

        levels = _pcm_s16le_pair_levels(chunk, 4, [3, 4])

        self.assertAlmostEqual(levels["left"]["peak"], 1.0)
        self.assertAlmostEqual(levels["right"]["peak"], 0.25)


class _TimeoutSpeakerProcess:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.returncode: int | None = None
        self.terminated = False
        self._communicate_count = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self._communicate_count += 1
        if self._communicate_count == 1:
            raise subprocess.TimeoutExpired(self.command, timeout)
        self.returncode = -15
        return "", "terminated gst pipeline"

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.returncode = -9


class _ExitedSpeakerProcess:
    def __init__(self, command: list[str], returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return self.stdout, self.stderr


if __name__ == "__main__":
    unittest.main()
