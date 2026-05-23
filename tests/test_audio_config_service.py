from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_app.services.config_service import ConfigService, ConfigValidationError


class AudioConfigServiceTests(unittest.TestCase):
    def make_service(self, text: str) -> ConfigService:
        self.tempdir = tempfile.TemporaryDirectory()
        path = Path(self.tempdir.name) / "config.yaml"
        path.write_text(text, encoding="utf-8")
        self.addCleanup(self.tempdir.cleanup)
        return ConfigService(path)

    def test_read_audio_settings_defaults_to_stereo_pairs(self) -> None:
        service = self.make_service(
            """
server_ip: 127.0.0.1
audio:
  rate: 48000
  channels: 2
receiver_audio:
  transport: aac
""".strip()
        )

        settings = service.read_audio_settings()

        self.assertEqual(settings["rate"], 48000)
        self.assertEqual(settings["capture_input_channels"], [1, 2])
        self.assertEqual(settings["sender_playback_output_channels"], [1, 2])
        self.assertEqual(settings["receiver_playback_output_channels"], [1, 2])
        self.assertEqual(settings["channels"], 2)

    def test_write_audio_settings_updates_audio_and_receiver_blocks(self) -> None:
        service = self.make_service(
            """
server_ip: 127.0.0.1
audio:
  device: default
  playback_device: default
  rate: 48000
  channels: 2
  format: S16BE
receiver_audio:
  transport: aac
  playback_device: default
""".strip()
        )

        parsed = service.write_audio_settings(
            {
                "rate": 48000,
                "capture_device": "hw:2,0",
                "capture_input_channels": [3, 4],
                "capture_hardware_channels": 8,
                "sender_playback_device": "hw:2,0",
                "sender_playback_output_channels": [5, 6],
                "sender_playback_hardware_channels": 10,
                "receiver_playback_device": "hw:3,0",
                "receiver_playback_output_channels": [7, 8],
                "receiver_playback_hardware_channels": 8,
            }
        )

        self.assertEqual(parsed["audio"]["device"], "hw:2,0")
        self.assertEqual(parsed["audio"]["capture_input_channels"], [3, 4])
        self.assertEqual(parsed["audio"]["capture_hardware_channels"], 8)
        self.assertEqual(parsed["audio"]["playback_output_channels"], [5, 6])
        self.assertEqual(parsed["receiver_audio"]["playback_output_channels"], [7, 8])
        self.assertEqual(parsed["audio"]["channels"], 2)

    def test_write_audio_settings_rejects_unsupported_dsp_rate(self) -> None:
        service = self.make_service("audio:\n  rate: 48000\nreceiver_audio:\n  transport: aac\n")

        with self.assertRaises(ConfigValidationError):
            service.write_audio_settings({"rate": 44100})


if __name__ == "__main__":
    unittest.main()
