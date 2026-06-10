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
        def find(_name):
            return None

    class _FakeSystemClock:
        @staticmethod
        def obtain():
            return object()

    class _FakeBuffer:
        @staticmethod
        def new_allocate(_allocator, size, _params):
            return _FakeBuffer(size)

        def __init__(self, size):
            self.size = size
            self.pts = None
            self.duration = None

        def fill(self, _offset, data):
            self.data = data

    class _FakeGst:
        ElementFactory = _FakeElementFactory
        SystemClock = _FakeSystemClock
        State = types.SimpleNamespace(PLAYING=object(), NULL=object())
        MessageType = types.SimpleNamespace(ERROR=object(), EOS=object())
        PadProbeType = types.SimpleNamespace(BUFFER=1)
        PadProbeReturn = types.SimpleNamespace(OK=object())
        FlowReturn = types.SimpleNamespace(OK=object(), FLUSHING=object(), ERROR=object())
        Buffer = _FakeBuffer
        SECOND = 1_000_000_000

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace(idle_add=lambda func, *args: func(*args))
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository


_MODULE_PATH = Path(__file__).resolve().parents[1] / "production" / "3_receiver" / "receive.py"
_SPEC = importlib.util.spec_from_file_location("receiver_receive_for_tests", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
receiver_receive = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(receiver_receive)
receiver_receive.GLib = types.SimpleNamespace(idle_add=lambda func, *args: func(*args))
receiver_receive.Gst.PadProbeType = types.SimpleNamespace(BUFFER=1)
receiver_receive.Gst.PadProbeReturn = types.SimpleNamespace(OK=object())
receiver_receive.Gst.FlowReturn = types.SimpleNamespace(OK=object(), FLUSHING=object(), ERROR=object())


class ReceiverFallbackTests(unittest.TestCase):
    def test_receiver_pipeline_uses_disconnect_fallback_appsrc_instead_of_snow(self) -> None:
        receiver = receiver_receive.VideoReceiver("tn", video_sink="fake")

        with patch.object(receiver_receive, "load_config", return_value=_config()):
            pipeline = receiver.build_pipeline()

        self.assertIn("appsrc name=disconnect_fallback_src", pipeline)
        self.assertIn("caps=video/x-raw,format=RGB,width=1920,height=1080,framerate=1/1", pipeline)
        self.assertIn("name=fallback ! selector.", pipeline)
        self.assertNotIn("videotestsrc pattern=snow", pipeline)

    def test_monitor_primary_stays_on_fallback_without_restarting_receiver(self) -> None:
        class Receiver(receiver_receive.VideoReceiver):
            def __init__(self):
                super().__init__("tn")
                self.stopped = False

            def stop(self):
                self.stopped = True

        receiver = Receiver()
        receiver.fallback_active = True
        receiver.fallback_started_at = 10.0

        self.assertTrue(receiver.monitor_primary())
        self.assertFalse(receiver.stopped)
        self.assertTrue(receiver.fallback_active)

    def test_fallback_push_retries_silently_when_active_pipeline_is_flushing(self) -> None:
        class FallbackSource:
            def frame(self):
                return b"abc"

        class AppSrc:
            def emit(self, _signal, _buffer):
                return receiver_receive.Gst.FlowReturn.FLUSHING

        receiver = receiver_receive.VideoReceiver("tn")
        receiver.pipeline = object()
        receiver.fallback_src = AppSrc()
        receiver.fallback_frame_source = FallbackSource()
        receiver.fallback_frames_running = True
        receiver.fallback_active = True

        self.assertTrue(receiver.push_fallback_frame())
        self.assertTrue(receiver.fallback_frames_running)

    def test_fallback_push_stops_timer_when_fallback_is_inactive(self) -> None:
        receiver = receiver_receive.VideoReceiver("tn")
        receiver.pipeline = object()
        receiver.fallback_src = object()
        receiver.fallback_frame_source = object()
        receiver.fallback_frames_running = True
        receiver.fallback_active = False

        self.assertFalse(receiver.push_fallback_frame())
        self.assertFalse(receiver.fallback_frames_running)

    def test_primary_buffer_probe_schedules_switch_back_to_primary(self) -> None:
        class Receiver(receiver_receive.VideoReceiver):
            def __init__(self):
                super().__init__("tn")
                self.switched = False

            def switch_to_primary(self):
                self.switched = True
                self.fallback_active = False

        receiver = Receiver()
        receiver.fallback_active = True
        info = types.SimpleNamespace(type=receiver_receive.Gst.PadProbeType.BUFFER)

        with patch.object(receiver_receive.time, "monotonic", return_value=123.0):
            result = receiver.primary_buffer_probe(None, info)

        self.assertEqual(receiver.last_primary_buffer_time, 123.0)
        self.assertTrue(receiver.switched)
        self.assertFalse(receiver.fallback_active)
        self.assertIs(result, receiver_receive.Gst.PadProbeReturn.OK)


def _config() -> dict:
    return {
        "server_ip": "100.119.85.108",
        "streaming_settings_video": "rbuf=327680&wbuf=327680&tsbpdDelay=100",
        "ports": {
            "video_receive_tn": 7704,
            "audio_receive_tn": 8808,
        },
        "receiver_audio": {"transport": "off", "playback_device": "default"},
        "audio": {"rate": 48000, "channels": 2, "encoding_name": "L16"},
    }


if __name__ == "__main__":
    unittest.main()
