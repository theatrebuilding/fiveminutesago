from __future__ import annotations

import sys
import types
import unittest

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
        Bus = object
        Message = object
        Buffer = object

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace()
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository

from control_app.services.server_runtime import (
    build_audio_relay_pipeline_string,
    build_audio_relay_pipeline_strings,
)


class ServerAudioRelayPipelineTests(unittest.TestCase):
    def test_relay_maps_sender_uplinks_to_opposite_dsp_return_ports(self) -> None:
        pipeline = build_audio_relay_pipeline_string(_config())

        self.assertIn("uri=srt://:8805?mode=listener", pipeline)
        self.assertIn("uri=srt://:8806?mode=listener", pipeline)
        self.assertIn("srtsink name=a_recv_dk uri=srt://:8807?mode=listener", pipeline)
        self.assertIn("srtsink name=a_recv_tn uri=srt://:8808?mode=listener", pipeline)
        self.assertIn("identity name=audio_diag_tn_uplink signal-handoffs=true silent=true", pipeline)
        self.assertIn("identity name=audio_diag_dk_uplink signal-handoffs=true silent=true", pipeline)
        self.assertIn("identity name=audio_diag_tn_to_dk_return signal-handoffs=true silent=true", pipeline)
        self.assertIn("identity name=audio_diag_dk_to_tn_return signal-handoffs=true silent=true", pipeline)

    def test_relay_directions_are_isolated_into_separate_pipelines(self) -> None:
        pipelines = build_audio_relay_pipeline_strings(_config())

        self.assertEqual(set(pipelines), {"audio-tn-to-dk", "audio-dk-to-tn"})
        self.assertIn("uri=srt://:8805?mode=listener", pipelines["audio-tn-to-dk"])
        self.assertIn("srtsink name=a_recv_dk uri=srt://:8807?mode=listener", pipelines["audio-tn-to-dk"])
        self.assertNotIn("8806", pipelines["audio-tn-to-dk"])
        self.assertNotIn("8808", pipelines["audio-tn-to-dk"])
        self.assertIn("uri=srt://:8806?mode=listener", pipelines["audio-dk-to-tn"])
        self.assertIn("srtsink name=a_recv_tn uri=srt://:8808?mode=listener", pipelines["audio-dk-to-tn"])
        self.assertNotIn("8805", pipelines["audio-dk-to-tn"])
        self.assertNotIn("8807", pipelines["audio-dk-to-tn"])


def _config() -> dict:
    return {
        "streaming_settings_audio": "rbuf=327680&wbuf=327680&tsbpdDelay=100",
        "ports": {
            "audio_send_tn": 8805,
            "audio_send_dk": 8806,
            "audio_receive_dk": 8807,
            "audio_receive_tn": 8808,
        },
        "audio": {
            "format": "S16BE",
            "rate": 48000,
            "channels": 2,
            "encoding_name": "L16",
        },
    }


if __name__ == "__main__":
    unittest.main()
