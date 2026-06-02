from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch


try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda _file: {})

if "gi" not in sys.modules:
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args, **_kwargs: None
    repository = types.ModuleType("gi.repository")

    class _FakeElementFactory:
        @staticmethod
        def find(name):
            return object() if name == "voaacenc" else None

    class _FakeSystemClock:
        @staticmethod
        def obtain():
            return object()

    class _FakeGst:
        ElementFactory = _FakeElementFactory
        SystemClock = _FakeSystemClock
        State = types.SimpleNamespace(PLAYING=object(), NULL=object())
        MessageType = types.SimpleNamespace(ERROR=object(), EOS=object())
        StateChangeReturn = types.SimpleNamespace(FAILURE=object(), ASYNC=object())
        CLOCK_TIME_NONE = 0

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace(MainLoop=object, timeout_add=lambda *_args, **_kwargs: None)
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository


_MODULE_PATH = Path(__file__).resolve().parents[1] / "production" / "1_sender" / "send.py"
_SPEC = importlib.util.spec_from_file_location("sender_send_for_tests", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sender_send = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sender_send)


class SenderPipelineCapsTests(unittest.TestCase):
    def test_audio_caps_use_explicit_capsfilters_in_playback_dsp_pipeline(self) -> None:
        runtime = sender_send.SenderRuntime(
            country="tn",
            video_device="/host-dev/video0",
            audio_enabled=True,
            audio_device="hw:3,0",
            playback_device="hw:3,0",
            local_audio_rate=48000,
            sender_audio_mode="aec",
            preview_pattern="/tmp/sender-preview-%05d.jpg",
        )

        with patch.object(sender_send, "load_config", return_value=_config()):
            pipeline = runtime.build_pipeline()

        self.assertIn("webrtcdsp probe=playback_probe", pipeline)
        self.assertIn("capsfilter caps=audio/x-raw,format=S16LE", pipeline)
        self.assertIn("capsfilter caps=audio/x-raw,format=S16BE", pipeline)
        self.assertNotIn("! audio/x-raw", pipeline)

    def test_audio_caps_use_explicit_capsfilters_in_capture_only_pipeline(self) -> None:
        runtime = sender_send.SenderRuntime(
            country="tn",
            video_device="/host-dev/video0",
            audio_enabled=True,
            audio_device="hw:3,0",
            local_audio_rate=48000,
            sender_audio_mode="capture-only",
            preview_pattern="/tmp/sender-preview-%05d.jpg",
        )

        with patch.object(sender_send, "load_config", return_value=_config()):
            pipeline = runtime.build_pipeline()

        self.assertNotIn("webrtcdsp probe=playback_probe", pipeline)
        self.assertIn("capsfilter caps=audio/x-raw,format=S16LE", pipeline)
        self.assertNotIn("! audio/x-raw", pipeline)


def _config() -> dict:
    return {
        "server_ip": "100.119.85.108",
        "streaming_settings_audio": "rbuf=327680&wbuf=327680&tsbpdDelay=100",
        "streaming_settings_video": "rbuf=327680&wbuf=327680&tsbpdDelay=100",
        "ports": {
            "audio_send_tn": 8805,
            "audio_receive_tn": 8808,
            "video_send_tn": 7701,
        },
        "audio": {
            "device": "default",
            "playback_device": "default",
            "format": "S16BE",
            "rate": 48000,
            "channels": 2,
            "encoding_name": "L16",
            "aac_encoder": "voaacenc bitrate=320000",
        },
        "video": {
            "source": "v4l2src device=/dev/video0",
            "width": 1920,
            "height": 1080,
            "encoder": "x264enc",
            "tune": "zerolatency",
            "bitrate": 5000,
            "key_int_max": 30,
            "framerate": 30,
            "bframes": 0,
            "aud": True,
            "byte_stream": True,
            "profile": "high",
            "speed_preset": "ultrafast",
            "config_interval": 1,
            "alignment": 7,
        },
        "webrtcdsp_settings": {
            "compression-gain-db": 5,
            "echo-cancel": True,
            "echo-suppression-level": "high",
            "gain-control": False,
            "noise-suppression": False,
            "noise-suppression-level": "high",
        },
    }


if __name__ == "__main__":
    unittest.main()
