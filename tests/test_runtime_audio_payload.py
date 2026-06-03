from __future__ import annotations

import unittest
import sys
import types


try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda _file: {})

if "gi" not in sys.modules:
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args, **_kwargs: None
    repository = types.ModuleType("gi.repository")

    class _FakeGst:
        Pad = object
        Pipeline = object
        Element = object

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace()
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository

from control_app.services.runtime_service import RuntimeLaunchRequest


class RuntimeAudioPayloadTests(unittest.TestCase):
    def test_sender_local_audio_routing_payload_ignores_sample_rate(self) -> None:
        request = RuntimeLaunchRequest.from_payload(
            {
                "role": "sender",
                "country": "tn",
                "audio_source": "device",
                "audio_device": "hw:2,0",
                "sender_audio_mode": "aec",
                "sender_playback_device": "hw:2,0",
                "sender_audio_rate": 48000,
                "sender_capture_input_channels": [3, 4],
                "sender_capture_hardware_channels": 8,
                "sender_playback_output_channels": [5, 6],
                "sender_playback_hardware_channels": 10,
                "video_source": "test",
            }
        )

        self.assertIsNone(request.sender_audio_rate)
        self.assertEqual(request.sender_capture_input_channels, (3, 4))
        self.assertEqual(request.sender_capture_hardware_channels, 8)
        self.assertEqual(request.sender_playback_output_channels, (5, 6))
        self.assertEqual(request.sender_playback_hardware_channels, 10)
        self.assertEqual(request.to_dict()["sender_capture_input_channels"], [3, 4])

    def test_sender_audio_off_clears_local_audio_settings(self) -> None:
        request = RuntimeLaunchRequest.from_payload(
            {
                "role": "sender",
                "country": "tn",
                "audio_source": "off",
                "sender_audio_rate": 48000,
                "sender_capture_input_channels": [3, 4],
                "sender_playback_output_channels": [5, 6],
                "video_source": "test",
            }
        )

        self.assertIsNone(request.sender_audio_rate)
        self.assertEqual(request.sender_capture_input_channels, (1, 2))
        self.assertEqual(request.sender_playback_output_channels, (1, 2))

    def test_sender_playback_only_keeps_playback_routing_without_dsp(self) -> None:
        request = RuntimeLaunchRequest.from_payload(
            {
                "role": "sender",
                "country": "dk",
                "audio_source": "device",
                "audio_device": "hw:2,0",
                "sender_audio_mode": "playback-only",
                "sender_playback_device": "hw:3,0",
                "sender_playback_output_channels": [5, 6],
                "sender_playback_hardware_channels": 8,
                "sender_audio_delay_ms": 120,
                "video_source": "test",
            }
        )

        self.assertEqual(request.sender_audio_mode, "playback-only")
        self.assertEqual(request.sender_playback_device, "hw:3,0")
        self.assertEqual(request.sender_playback_output_channels, (5, 6))
        self.assertEqual(request.sender_playback_hardware_channels, 8)
        self.assertEqual(request.sender_audio_delay_ms, 120)

    def test_invalid_channel_pair_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeLaunchRequest.from_payload(
                {
                    "role": "sender",
                    "country": "tn",
                    "audio_source": "device",
                    "sender_capture_input_channels": [2, 3],
                    "video_source": "test",
                }
            )

    def test_receiver_defaults_to_video_only_audio_off(self) -> None:
        request = RuntimeLaunchRequest.from_payload(
            {
                "role": "receiver",
                "country": "dk",
            }
        )

        self.assertEqual(request.receiver_audio_transport, "off")
        self.assertIsNone(request.receiver_playback_device)

    def test_receiver_debug_l16_audio_can_still_be_requested_explicitly(self) -> None:
        request = RuntimeLaunchRequest.from_payload(
            {
                "role": "receiver",
                "country": "dk",
                "receiver_audio_transport": "l16",
                "receiver_playback_device": "hw:2,0",
            }
        )

        self.assertEqual(request.receiver_audio_transport, "l16")
        self.assertEqual(request.receiver_playback_device, "hw:2,0")


if __name__ == "__main__":
    unittest.main()
