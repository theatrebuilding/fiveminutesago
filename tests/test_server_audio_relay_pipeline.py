from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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

import control_app.services.server_runtime as server_runtime
from control_app.services.server_runtime import (
    ServerRuntime,
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

    def test_pipeline_teardown_removes_bus_watch_before_dropping_listener_pipeline(self) -> None:
        with _patched_gst_for_teardown():
            runtime = ServerRuntime(
                config_path=Path("config.yaml"),
                recording_dir=Path("recordings"),
                archive_dir=Path("archive"),
                preview_dir=Path("previews"),
            )
            pipeline = _FakePipeline()

            runtime._configure_bus(pipeline, "audio-tn-to-dk", lambda _bus, _message: True)
            runtime._teardown_pipeline(pipeline, "audio-tn-to-dk", suppress_errors=True)

        self.assertEqual(pipeline.bus.disconnected_handlers, [1])
        self.assertEqual(pipeline.bus.remove_signal_watch_count, 1)
        self.assertTrue(pipeline.bus.flushing)
        self.assertEqual(pipeline.states, ["NULL"])
        self.assertNotIn("audio-tn-to-dk", runtime._pipeline_bus_watches)

    def test_server_start_continues_when_audio_relay_initial_arm_fails(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        logs: list[str] = []
        runtime._log_callback = logs.append
        started_video_feeds: list[str] = []
        scheduled_retries: list[tuple] = []

        with _patched_gst_for_teardown(), patch.object(
            server_runtime, "_load_config", return_value=_server_config()
        ), patch.object(
            server_runtime, "UdpPacketMonitor", _FakePacketMonitor
        ), patch.object(
            runtime, "_build_audio_pipelines", return_value={"audio-tn-to-dk": object()}
        ), patch.object(
            runtime, "_configure_audio_diagnostics"
        ), patch.object(
            runtime, "_configure_bus"
        ), patch.object(
            runtime,
            "_set_pipeline_state",
            side_effect=RuntimeError("[audio-tn-to-dk] Could not change pipeline state to PLAYING."),
        ), patch.object(
            runtime,
            "_start_video_feed",
            side_effect=lambda feed_state: started_video_feeds.append(feed_state.feed),
        ), patch.object(
            server_runtime.GLib,
            "timeout_add_seconds",
            create=True,
            side_effect=lambda *args: scheduled_retries.append(args) or 1,
        ):
            runtime._start_runtime()

        self.assertTrue(runtime.snapshot()["running"])
        self.assertEqual(started_video_feeds, ["tn", "dk"])
        self.assertTrue(any("server will keep starting" in line for line in logs))
        self.assertTrue(any(args[1] == runtime._restart_audio_pipeline for args in scheduled_retries))


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


def _server_config() -> dict:
    config = _config()
    config["ports"].update(
        {
            "video_send_tn": 8891,
            "video_receive_dk": 8892,
            "video_send_dk": 8893,
            "video_receive_tn": 8894,
        }
    )
    return config


class _FakePacketMonitor:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def snapshot(self) -> dict:
        return {}


class _patched_gst_for_teardown:
    def __enter__(self):
        self.original_gst = server_runtime.Gst
        server_runtime.Gst = types.SimpleNamespace(
            State=types.SimpleNamespace(NULL="NULL", PLAYING="PLAYING"),
            StateChangeReturn=types.SimpleNamespace(
                FAILURE="FAILURE",
                ASYNC="ASYNC",
                NO_PREROLL="NO_PREROLL",
            ),
            SECOND=1,
            Element=types.SimpleNamespace(state_get_name=lambda state: str(state)),
        )
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        server_runtime.Gst = self.original_gst


class _FakeBus:
    def __init__(self) -> None:
        self.add_signal_watch_count = 0
        self.remove_signal_watch_count = 0
        self.disconnected_handlers: list[int] = []
        self.flushing = False

    def add_signal_watch(self) -> None:
        self.add_signal_watch_count += 1

    def connect(self, _signal: str, _handler) -> int:
        return 1

    def disconnect(self, handler_id: int) -> None:
        self.disconnected_handlers.append(handler_id)

    def remove_signal_watch(self) -> None:
        self.remove_signal_watch_count += 1

    def set_flushing(self, value: bool) -> None:
        self.flushing = value


class _FakePipeline:
    def __init__(self) -> None:
        self.bus = _FakeBus()
        self.states: list[str] = []

    def get_bus(self) -> _FakeBus:
        return self.bus

    def set_state(self, state: str) -> str:
        self.states.append(state)
        return "SUCCESS"

    def get_state(self, _timeout_ns: int) -> tuple[str, str, None]:
        return "SUCCESS", self.states[-1], None


if __name__ == "__main__":
    unittest.main()
