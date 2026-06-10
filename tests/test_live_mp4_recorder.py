from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

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

        def __init__(self, size=0):
            self.size = size
            self.pts = None
            self.dts = None
            self.duration = None
            self.data = b""

        def fill(self, _offset, data):
            self.data = data

    class _FakeCaps:
        @staticmethod
        def from_string(value):
            return value

    class _FakeGst:
        ElementFactory = _FakeElementFactory
        SystemClock = _FakeSystemClock
        State = types.SimpleNamespace(PLAYING=object(), NULL=object())
        StateChangeReturn = types.SimpleNamespace(FAILURE=object(), ASYNC=object(), NO_PREROLL=object())
        MessageType = types.SimpleNamespace(ERROR=object(), EOS=object())
        PadProbeType = types.SimpleNamespace(BUFFER=1)
        PadProbeReturn = types.SimpleNamespace(OK=object(), DROP=object())
        FlowReturn = types.SimpleNamespace(OK=object(), FLUSHING=object(), ERROR=object())
        Format = types.SimpleNamespace(TIME=object())
        MapFlags = types.SimpleNamespace(READ=object())
        BufferFlags = types.SimpleNamespace(DELTA_UNIT=1)
        Caps = _FakeCaps
        Pad = object
        Pipeline = object
        Element = object
        Buffer = _FakeBuffer
        CLOCK_TIME_NONE = -1
        SECOND = 1_000_000_000

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace()
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository

from control_app.services.live_mp4_recorder import LiveMp4Recorder, RecordingPaths


class LiveMp4RecorderFallbackTests(unittest.TestCase):
    def test_raw_fallback_creates_video_mp4_audio_m4a_and_preserves_ts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _paths(root)
            paths.raw_temp_path.write_bytes(b"mpeg-ts-data")
            paths.temp_path.write_bytes(b"partial-mp4")
            logs: list[str] = []
            recorder = LiveMp4Recorder("dk", paths, audio_bitrate=320000, log_callback=logs.append)

            def fake_run(command, **_kwargs):
                output = Path(command[-1])
                output.write_bytes(b"output")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch("control_app.services.live_mp4_recorder.subprocess.run", side_effect=fake_run) as run:
                recorder._finalize_with_raw_fallback("audio mux failed")

            self.assertTrue(paths.final_path.exists())
            self.assertTrue(paths.raw_final_path.exists())
            self.assertTrue(paths.audio_fallback_path.exists())
            self.assertFalse(paths.raw_temp_path.exists())
            self.assertFalse(paths.temp_path.exists())
            self.assertEqual(run.call_count, 2)
            self.assertTrue(any("Final video-only archive ready" in message for message in logs))

    def test_raw_fallback_retries_with_video_transcode_when_copy_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _paths(root)
            paths.raw_temp_path.write_bytes(b"mpeg-ts-data")
            recorder = LiveMp4Recorder("tn", paths)
            calls: list[list[str]] = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if len(calls) == 1:
                    return types.SimpleNamespace(returncode=1, stderr="copy failed")
                Path(command[-1]).write_bytes(b"output")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch("control_app.services.live_mp4_recorder.subprocess.run", side_effect=fake_run):
                recorder._finalize_with_raw_fallback("live mux failed")

            self.assertTrue(paths.final_path.exists())
            self.assertIn("copy", calls[0])
            self.assertIn("libx264", calls[1])


def _paths(root: Path) -> RecordingPaths:
    return RecordingPaths(
        temp_path=root / "video_dk_20260609120000.recording.mp4",
        final_path=root / "video_dk_20260609120000.mp4",
        failed_path=root / "video_dk_20260609120000.failed.mp4",
        raw_temp_path=root / "video_dk_20260609120000.recording.ts",
        raw_final_path=root / "video_dk_20260609120000.ts",
        audio_fallback_path=root / "video_dk_20260609120000.audio.m4a",
    )


if __name__ == "__main__":
    unittest.main()
