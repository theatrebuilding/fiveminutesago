from __future__ import annotations

import unittest

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

    def test_speaker_test_commands_use_runtime_device_and_selected_channels(self) -> None:
        service = AudioDeviceService()

        commands = service.build_speaker_test_commands(
            {
                "device": "hw:2,0",
                "rate": 48000,
                "output_channels": [5, 6],
                "hardware_channels": 10,
            }
        )

        self.assertEqual(commands[0][:3], ["speaker-test", "-D", "plughw:2,0"])
        self.assertIn("-c", commands[0])
        self.assertEqual(commands[0][commands[0].index("-c") + 1], "10")
        self.assertEqual(commands[0][commands[0].index("-s") + 1], "5")
        self.assertEqual(commands[1][commands[1].index("-s") + 1], "6")

    def test_capture_level_command_uses_plughw_and_caps_duration(self) -> None:
        service = AudioDeviceService()

        command, metadata = service.build_capture_level_command(
            {
                "device": "hw:2,0",
                "rate": 96000,
                "input_channels": [3, 4],
                "supported_channel_counts": [2, 12],
                "duration_seconds": 99,
            }
        )

        self.assertEqual(command[:4], ["arecord", "-q", "-D", "plughw:2,0"])
        self.assertIn("S16_LE", command)
        self.assertEqual(command[command.index("-r") + 1], "96000")
        self.assertEqual(command[command.index("-c") + 1], "12")
        self.assertEqual(command[command.index("-d") + 1], "10")
        self.assertEqual(metadata["input_channels"], [3, 4])

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


if __name__ == "__main__":
    unittest.main()
