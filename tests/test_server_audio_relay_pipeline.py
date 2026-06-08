from __future__ import annotations

import sys
import tempfile
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
        self.assertNotIn("rtpjitterbuffer", pipeline)
        self.assertNotIn("rtpL16depay", pipeline)
        self.assertNotIn("rtpL16pay", pipeline)
        self.assertNotIn("audio/x-raw", pipeline)
        self.assertIn("rbuf=1048576&wbuf=1048576&tsbpdDelay=500", pipeline)
        self.assertIn("max-size-time=500000000", pipeline)

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
        "streaming_settings_audio": "rbuf=1048576&wbuf=1048576&tsbpdDelay=500",
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
        "live_queues": {
            "server": {
                "audio_input": {
                    "max_size_buffers": 0,
                    "max_size_bytes": 0,
                    "max_size_time_ms": 500,
                },
                "audio_output": {
                    "max_size_buffers": 0,
                    "max_size_bytes": 0,
                    "max_size_time_ms": 500,
                },
            },
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


class ServerArchivePlaybackTests(unittest.TestCase):
    def test_archive_candidates_filter_by_feed_prefix_and_ignore_incomplete_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            keep_tn = archive_dir / "video_tn_20260101010101.mp4"
            keep_dk = archive_dir / "video_dk_20260101010101.mp4"
            ignored_failed = archive_dir / "video_tn_20260101010101.failed.mp4"
            ignored_recording = archive_dir / "video_tn_20260101010101.recording.mp4"
            ignored_other = archive_dir / "notes.mp4"
            for path in (keep_tn, keep_dk, ignored_failed, ignored_recording, ignored_other):
                path.write_bytes(b"x")

            self.assertEqual(server_runtime.archive_candidates_for_feed(archive_dir, "tn"), [keep_tn])
            self.assertEqual(server_runtime.archive_candidates_for_feed(archive_dir, "dk"), [keep_dk])

    def test_archive_feed_prefixes_send_opposite_country_recordings_to_receivers(self) -> None:
        # The server's `tn` feed is routed to the DK receiver; its archive source must be video_tn_*.
        # The server's `dk` feed is routed to the TN receiver; its archive source must be video_dk_*.
        self.assertEqual(server_runtime.archive_prefix_for_feed("tn"), "video_tn_")
        self.assertEqual(server_runtime.archive_prefix_for_feed("dk"), "video_dk_")

    def test_archive_audio_receive_ports_target_opposite_sender_pcm_streams(self) -> None:
        ports = _server_config()["ports"]

        self.assertEqual(server_runtime.archive_audio_receive_port_for_feed(ports, "tn"), 8807)
        self.assertEqual(server_runtime.archive_audio_receive_port_for_feed(ports, "dk"), 8808)

    def test_random_archive_start_offset_uses_duration_when_available(self) -> None:
        with patch.object(server_runtime.random, "uniform", return_value=12.5) as uniform:
            offset = server_runtime.random_archive_start_offset(60.0)

        self.assertEqual(offset, 12.5)
        uniform.assert_called_once_with(0.0, 59.0)
        self.assertEqual(server_runtime.random_archive_start_offset(None), 0.0)
        self.assertEqual(server_runtime.random_archive_start_offset(0.5), 0.0)

    def test_archive_video_pipeline_reads_file_and_sends_to_receiver_port(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        feed_state = server_runtime.VideoFeedState("tn", 7701, 7703, "tn-%05d.jpg")
        selection = server_runtime.ArchivePlaybackSelection(
            feed="tn",
            file_path=Path('/archive/video_tn_sample.mp4'),
            start_offset_seconds=3.0,
            duration_seconds=20.0,
        )

        with patch.object(server_runtime, "_load_config", return_value=_server_config()), patch.object(
            server_runtime.Gst, "parse_launch", side_effect=lambda pipeline: pipeline, create=True
        ):
            pipeline = runtime._build_archive_video_pipeline(feed_state, selection)

        self.assertIn('filesrc name=tn_archive_source location="/archive/video_tn_sample.mp4"', pipeline)
        self.assertIn("qtdemux name=tn_archive_demux", pipeline)
        self.assertIn("mpegtsmux name=tn_archive_mux alignment=7", pipeline)
        self.assertIn('srtsink name=tn_relay uri="srt://:7703?mode=listener', pipeline)
        self.assertIn("audio/mpeg,mpegversion=4", pipeline)
        self.assertIn("avdec_aac", pipeline)
        self.assertIn("audio/x-raw,format=S16BE,layout=interleaved,channels=2,rate=48000", pipeline)
        self.assertIn("rtpL16pay mtu=600", pipeline)
        self.assertIn("application/x-rtp,media=audio,clock-rate=48000,encoding-name=L16,channels=2", pipeline)
        self.assertIn('srtsink name=tn_archive_audio_relay uri="srt://:8807?mode=listener', pipeline)
        self.assertIn("h264parse name=tn_preview_h264parse", pipeline)

    def test_archive_dk_pipeline_sends_recorded_audio_to_tn_pcm_port(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        feed_state = server_runtime.VideoFeedState("dk", 7702, 7704, "dk-%05d.jpg")
        selection = server_runtime.ArchivePlaybackSelection(
            feed="dk",
            file_path=Path('/archive/video_dk_sample.mp4'),
            start_offset_seconds=5.0,
            duration_seconds=30.0,
        )

        with patch.object(server_runtime, "_load_config", return_value=_server_config()), patch.object(
            server_runtime.Gst, "parse_launch", side_effect=lambda pipeline: pipeline, create=True
        ):
            pipeline = runtime._build_archive_video_pipeline(feed_state, selection)

        self.assertIn('filesrc name=dk_archive_source location="/archive/video_dk_sample.mp4"', pipeline)
        self.assertIn('srtsink name=dk_relay uri="srt://:7704?mode=listener', pipeline)
        self.assertIn('srtsink name=dk_archive_audio_relay uri="srt://:8808?mode=listener', pipeline)
        self.assertNotIn('dk_archive_audio_relay uri="srt://:8807', pipeline)

    def test_audio_relay_restart_is_suppressed_during_archive_playback(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        logs: list[str] = []
        runtime._log_callback = logs.append
        runtime._running = True
        runtime._archive_playback_active = True

        with patch.object(runtime, "_build_audio_pipeline") as build_audio_pipeline:
            self.assertFalse(runtime._restart_audio_pipeline("audio-tn-to-dk"))

        build_audio_pipeline.assert_not_called()
        self.assertTrue(any("skipped while back-in-time mode is active" in line for line in logs))

    def test_start_archive_playback_releases_live_pcm_relays_before_archive_pipelines(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        runtime._running = True
        runtime._video_feeds = {
            "tn": server_runtime.VideoFeedState("tn", 7701, 7703, "tn-%05d.jpg"),
            "dk": server_runtime.VideoFeedState("dk", 7702, 7704, "dk-%05d.jpg"),
        }
        selections = {
            "tn": server_runtime.ArchivePlaybackSelection("tn", Path("/archive/video_tn_a.mp4"), 1.0, 10.0),
            "dk": server_runtime.ArchivePlaybackSelection("dk", Path("/archive/video_dk_b.mp4"), 2.0, 20.0),
        }
        calls: list[str] = []

        with patch.object(server_runtime, "_load_config", return_value=_server_config()), patch.object(
            runtime, "_select_archive_playback_files", return_value=selections
        ), patch.object(
            runtime, "_stop_audio_relay_pipelines", side_effect=lambda: calls.append("stop-audio")
        ), patch.object(
            runtime,
            "_start_archive_video_feed",
            side_effect=lambda feed_state, _selection: calls.append(f"archive-{feed_state.feed}"),
        ):
            runtime._start_archive_playback_on_loop()

        self.assertTrue(runtime._archive_playback_active)
        self.assertEqual(calls, ["stop-audio", "archive-tn", "archive-dk"])

    def test_stop_archive_playback_restores_live_pcm_relays_before_live_video(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        runtime._running = True
        runtime._archive_playback_active = True
        runtime._video_feeds = {
            "tn": server_runtime.VideoFeedState("tn", 7701, 7703, "tn-%05d.jpg"),
            "dk": server_runtime.VideoFeedState("dk", 7702, 7704, "dk-%05d.jpg"),
        }
        calls: list[str] = []

        with patch.object(server_runtime, "_load_config", return_value=_server_config()), patch.object(
            runtime, "_start_audio_relay_pipelines", side_effect=lambda _config: calls.append("start-audio") or []
        ), patch.object(
            runtime, "_start_video_feed", side_effect=lambda feed_state: calls.append(f"live-{feed_state.feed}")
        ):
            runtime._stop_archive_playback_on_loop()

        self.assertFalse(runtime._archive_playback_active)
        self.assertEqual(calls, ["start-audio", "live-tn", "live-dk"])

    def test_recording_cannot_start_while_archive_playback_is_active(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        runtime._running = True
        runtime._archive_playback_active = True

        with self.assertRaisesRegex(RuntimeError, "Resume present time"):
            runtime._start_recording_on_loop()

    def test_select_archive_playback_files_requires_both_feed_directions(self) -> None:
        runtime = ServerRuntime(
            config_path=Path("config.yaml"),
            recording_dir=Path("recordings"),
            archive_dir=Path("archive"),
            preview_dir=Path("previews"),
        )
        runtime._video_feeds = {
            "tn": server_runtime.VideoFeedState("tn", 7701, 7703, "tn-%05d.jpg"),
            "dk": server_runtime.VideoFeedState("dk", 7702, 7704, "dk-%05d.jpg"),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            tn_file = archive_dir / "video_tn_a.mp4"
            dk_file = archive_dir / "video_dk_b.mp4"
            tn_file.write_bytes(b"tn")
            dk_file.write_bytes(b"dk")
            runtime._archive_dir = archive_dir

            with patch.object(server_runtime, "_probe_media_duration_seconds", return_value=30.0), patch.object(
                server_runtime.random, "choice", side_effect=lambda values: values[0]
            ), patch.object(server_runtime.random, "uniform", return_value=7.0):
                selections = runtime._select_archive_playback_files()

        self.assertEqual(selections["tn"].file_path.name, "video_tn_a.mp4")
        self.assertEqual(selections["dk"].file_path.name, "video_dk_b.mp4")
        self.assertEqual(selections["tn"].start_offset_seconds, 7.0)
        self.assertEqual(selections["dk"].duration_seconds, 30.0)


if __name__ == "__main__":
    unittest.main()
