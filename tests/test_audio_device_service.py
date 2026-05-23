from __future__ import annotations

import unittest

from control_app.services.audio_device_service import AudioDeviceService


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


if __name__ == "__main__":
    unittest.main()
