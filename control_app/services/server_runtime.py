from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
from pathlib import Path
import threading
import time
from typing import Any, Callable

import gi
import yaml

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from live_queue_settings import build_queue_element
from .live_mp4_recorder import LiveMp4Recorder, RecordingPaths
from .preview_catalog import build_server_preview_pattern, describe_latest_preview, prune_preview_files
from .udp_packet_monitor import UdpPacketMonitor


Gst.init(None)

PREVIEW_FRAME_INTERVAL_SECONDS = 5.0
PACKETS_WITHOUT_DECODE_WARNING_SECONDS = 20.0
PACKETS_WITHOUT_DECODE_RESTART_SECONDS = 30.0
AUDIO_DIAGNOSTIC_LOG_SECONDS = 5
AUDIO_DIAGNOSTIC_ELEMENTS = {
    "audio_diag_tn_uplink": "TN mic uplink",
    "audio_diag_dk_uplink": "DK mic uplink",
    "audio_diag_tn_to_dk_return": "TN -> DK return",
    "audio_diag_dk_to_tn_return": "DK -> TN return",
}


@dataclass
class RecordingSession:
    recorder: LiveMp4Recorder
    tee_sink_pad: Gst.Pad | None = None
    probe_id: int | None = None


@dataclass
class VideoFeedState:
    feed: str
    send_port: int
    receive_port: int
    preview_pattern: str
    pipeline: Gst.Pipeline | None = None
    tee: Gst.Element | None = None
    recording_session: RecordingSession | None = None


class ServerRuntime:
    def __init__(
        self,
        config_path: Path,
        recording_dir: Path,
        archive_dir: Path,
        preview_dir: Path,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._config_path = config_path
        self._recording_dir = recording_dir
        self._archive_dir = archive_dir
        self._preview_dir = preview_dir
        self._log_callback = log_callback

        self._lock = threading.Lock()
        self._main_loop: GLib.MainLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._audio_pipeline: Gst.Pipeline | None = None
        self._packet_monitor: UdpPacketMonitor | None = None
        self._video_feeds: dict[str, VideoFeedState] = {}
        self._recording_active = False
        self._recording_started_at: float | None = None
        self._recording_files: dict[str, RecordingPaths] = {}
        self._finalization_active_count = 0
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_exit_code: int | None = None
        self._running = False
        self._last_preview_log_at: dict[str, float] = {}
        self._last_continuity_warning_at: dict[str, float] = {}
        self._next_preview_frame_at: dict[str, float] = {}
        self._last_decoded_frame_at: dict[str, float] = {}
        self._video_decode_missing_since: dict[str, float] = {}
        self._last_no_decode_restart_at: dict[str, float] = {}
        self._audio_diagnostic_counts: dict[str, int] = {name: 0 for name in AUDIO_DIAGNOSTIC_ELEMENTS}
        self._last_audio_diagnostic_counts: dict[str, int] = dict(self._audio_diagnostic_counts)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self.snapshot()

            self._main_loop = GLib.MainLoop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="server-runtime-loop",
                daemon=True,
            )
            self._loop_thread.start()

        self._run_on_loop(self._start_runtime)
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running and self._main_loop is None:
                return self.snapshot()
            loop = self._main_loop
            loop_thread = self._loop_thread

        self._run_on_loop(self._stop_runtime, timeout=300)

        if loop is not None:
            GLib.idle_add(self._quit_loop)
        if loop_thread is not None:
            loop_thread.join(timeout=10)

        with self._lock:
            self._main_loop = None
            self._loop_thread = None

        return self.snapshot()

    def start_recording(self) -> dict[str, Any]:
        self._run_on_loop(self._start_recording_on_loop)
        return self.snapshot()

    def stop_recording(self) -> dict[str, Any]:
        self._run_on_loop(self._stop_recording_on_loop, timeout=300)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            packet_activity = self._packet_monitor.snapshot() if self._packet_monitor is not None else {}
            previews = {
                feed: self._preview_snapshot(feed, feed_state.preview_pattern, packet_activity.get(feed))
                for feed, feed_state in self._video_feeds.items()
            }
            return {
                "running": self._running,
                "started_at": _to_iso(self._started_at),
                "started_at_ts": self._started_at,
                "stopped_at": _to_iso(self._stopped_at),
                "stopped_at_ts": self._stopped_at,
                "last_exit_code": self._last_exit_code,
                "recording": {
                    "active": self._recording_active,
                    "finalizing": self._finalization_active_count > 0,
                    "started_at": _to_iso(self._recording_started_at),
                    "started_at_ts": self._recording_started_at,
                    "files": {
                        feed: str(paths.temp_path) for feed, paths in self._recording_files.items()
                    },
                },
                "packet_activity": packet_activity,
                "previews": previews,
            }

    def get_preview_path(self, feed: str) -> Path | None:
        with self._lock:
            feed_state = self._video_feeds.get(feed)
            if feed_state is None:
                return None
            preview = describe_latest_preview(self._preview_dir, feed_state.preview_pattern)
            path = preview.get("path")
            return Path(path) if path else None

    def _run_loop(self) -> None:
        loop: GLib.MainLoop | None
        with self._lock:
            loop = self._main_loop
        if loop is None:
            return
        loop.run()

    def _quit_loop(self) -> bool:
        with self._lock:
            loop = self._main_loop
        if loop is not None and loop.is_running():
            loop.quit()
        return False

    def _run_on_loop(self, func: Callable[[], Any], timeout: float = 20) -> Any:
        with self._lock:
            loop = self._main_loop
        if loop is None:
            raise RuntimeError("Server runtime loop is not available.")

        result: dict[str, Any] = {}
        done = threading.Event()

        def invoke() -> bool:
            try:
                result["value"] = func()
            except Exception as exc:  # pragma: no cover - runtime errors are surfaced through API/logs
                result["error"] = exc
            finally:
                done.set()
            return False

        GLib.idle_add(invoke)
        if not done.wait(timeout=timeout):
            raise RuntimeError("Server runtime operation timed out.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _start_runtime(self) -> None:
        config = _load_config(self._config_path)
        self._recording_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._preview_dir.mkdir(parents=True, exist_ok=True)

        ports = config.get("ports", {})
        self._video_feeds = {
            "tn": VideoFeedState(
                feed="tn",
                send_port=int(ports["video_send_tn"]),
                receive_port=int(ports["video_receive_dk"]),
                preview_pattern=build_server_preview_pattern(self._preview_dir, "tn"),
            ),
            "dk": VideoFeedState(
                feed="dk",
                send_port=int(ports["video_send_dk"]),
                receive_port=int(ports["video_receive_tn"]),
                preview_pattern=build_server_preview_pattern(self._preview_dir, "dk"),
            ),
        }
        for feed_state in self._video_feeds.values():
            prune_preview_files(self._preview_dir, feed_state.preview_pattern, keep=0)

        try:
            self._packet_monitor = UdpPacketMonitor(
                {feed: feed_state.send_port for feed, feed_state in self._video_feeds.items()},
                log_callback=self._log,
            )
            self._packet_monitor.start()

            self._audio_pipeline = self._build_audio_pipeline(config)
            self._configure_audio_diagnostics(self._audio_pipeline)
            self._configure_bus(self._audio_pipeline, "audio", self._on_audio_message)
            self._set_pipeline_state(self._audio_pipeline, Gst.State.PLAYING, "audio", allow_pending=True)
            GLib.timeout_add_seconds(AUDIO_DIAGNOSTIC_LOG_SECONDS, self._log_audio_diagnostics)

            self._last_preview_log_at = {}
            self._last_continuity_warning_at = {}
            self._next_preview_frame_at = {}
            self._last_decoded_frame_at = {}
            self._video_decode_missing_since = {}
            self._last_no_decode_restart_at = {}

            for feed in self._video_feeds.values():
                self._start_video_feed(feed)
            GLib.timeout_add_seconds(5, self._check_video_decode_health)
        except Exception:
            for feed_state in self._video_feeds.values():
                if feed_state.pipeline is not None:
                    self._set_pipeline_state(
                        feed_state.pipeline,
                        Gst.State.NULL,
                        f"video-{feed_state.feed}",
                        timeout_seconds=5,
                        suppress_errors=True,
                    )
                    feed_state.pipeline = None
                    feed_state.tee = None
                    feed_state.recording_session = None
            if self._audio_pipeline is not None:
                self._set_pipeline_state(
                    self._audio_pipeline,
                    Gst.State.NULL,
                    "audio",
                    timeout_seconds=5,
                    suppress_errors=True,
                )
                self._audio_pipeline = None
            if self._packet_monitor is not None:
                self._packet_monitor.stop()
                self._packet_monitor = None
            raise

        with self._lock:
            self._running = True
            self._started_at = time.time()
            self._stopped_at = None
            self._last_exit_code = None

        self._log("Server runtime started.")

    def _stop_runtime(self) -> None:
        with self._lock:
            self._running = False
            self._stopped_at = time.time()
            self._last_exit_code = 0

        self._stop_recording_on_loop()

        for feed_state in self._video_feeds.values():
            if feed_state.pipeline is not None:
                self._detach_recording_probe(feed_state)
                self._set_pipeline_state(feed_state.pipeline, Gst.State.NULL, f"video-{feed_state.feed}", timeout_seconds=10)
                feed_state.pipeline = None
                feed_state.tee = None
                feed_state.recording_session = None

        if self._audio_pipeline is not None:
            self._set_pipeline_state(self._audio_pipeline, Gst.State.NULL, "audio", timeout_seconds=10)
            self._audio_pipeline = None

        if self._packet_monitor is not None:
            self._packet_monitor.stop()
            self._packet_monitor = None

        self._log("Server runtime stopped.")

    def _start_video_feed(self, feed_state: VideoFeedState) -> None:
        pipeline = self._build_video_pipeline(feed_state)
        feed_state.pipeline = pipeline
        feed_state.tee = pipeline.get_by_name(f"{feed_state.feed}_stream_tee")
        self._configure_bus(
            pipeline,
            f"video-{feed_state.feed}",
            lambda bus, message, feed=feed_state.feed: self._on_video_message(bus, message, feed),
        )
        preview_parser = pipeline.get_by_name(f"{feed_state.feed}_preview_h264parse")
        if preview_parser is None:
            raise RuntimeError(f"Could not access preview parser for {feed_state.feed}.")
        preview_pad = preview_parser.get_static_pad("src")
        if preview_pad is None:
            raise RuntimeError(f"Could not access preview parser src pad for {feed_state.feed}.")
        self._next_preview_frame_at[feed_state.feed] = 0.0
        preview_pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self._throttle_preview_h264,
            feed_state.feed,
        )
        self._set_pipeline_state(
            pipeline,
            Gst.State.PLAYING,
            f"video-{feed_state.feed}",
            allow_pending=True,
        )
        if self._recording_active:
            record_paths = self._recording_files.get(feed_state.feed)
            if record_paths is not None:
                if feed_state.recording_session is None:
                    recording_config = _resolve_recording_config(_load_config(self._config_path))
                    self._arm_recording_session(feed_state, record_paths, recording_config)
                self._attach_recording_probe(feed_state)

    def _restart_video_feed(self, feed: str) -> bool:
        if not self._running:
            return False
        feed_state = self._video_feeds[feed]
        self._log(f"[{feed}] Restarting video pipeline.")

        if feed_state.pipeline is not None:
            self._detach_recording_probe(feed_state)
            self._set_pipeline_state(feed_state.pipeline, Gst.State.NULL, f"video-{feed}", timeout_seconds=10)
            feed_state.pipeline = None
            feed_state.tee = None
            self._next_preview_frame_at.pop(feed, None)
            self._last_decoded_frame_at.pop(feed, None)
            self._video_decode_missing_since.pop(feed, None)

        self._start_video_feed(feed_state)
        return False

    def _restart_audio_pipeline(self) -> bool:
        if not self._running:
            return False
        config = _load_config(self._config_path)
        self._log("[audio] Restarting audio pipeline.")

        if self._audio_pipeline is not None:
            self._set_pipeline_state(self._audio_pipeline, Gst.State.NULL, "audio", timeout_seconds=10)

        self._audio_pipeline = self._build_audio_pipeline(config)
        self._configure_audio_diagnostics(self._audio_pipeline)
        self._configure_bus(self._audio_pipeline, "audio", self._on_audio_message)
        self._set_pipeline_state(self._audio_pipeline, Gst.State.PLAYING, "audio", allow_pending=True)
        return False

    def _on_audio_message(self, bus: Gst.Bus, message: Gst.Message) -> bool:
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self._log(f"[audio] ERROR: {err}. {debug or ''}".strip())
            GLib.timeout_add_seconds(3, self._restart_audio_pipeline)
        elif message.type == Gst.MessageType.EOS:
            self._log("[audio] End of stream detected.")
            GLib.timeout_add_seconds(3, self._restart_audio_pipeline)
        return True

    def _on_video_message(self, bus: Gst.Bus, message: Gst.Message, feed: str) -> bool:
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self._log(f"[{feed}] ERROR: {err}. {debug or ''}".strip())
            GLib.timeout_add_seconds(3, self._restart_video_feed, feed)
        elif message.type == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            warning_text = str(err)
            if "CONTINUITY:" in warning_text:
                now = time.monotonic()
                last_logged_at = self._last_continuity_warning_at.get(feed)
                if last_logged_at is None or (now - last_logged_at) >= 10:
                    self._last_continuity_warning_at[feed] = now
                    self._log(
                        f"[{feed}] WARNING: TS continuity mismatches detected on the preview branch; preview frames may skip until the stream settles."
                    )
            else:
                self._log(f"[{feed}] WARNING: {err}. {debug or ''}".strip())
        elif message.type == Gst.MessageType.EOS:
            self._log(f"[{feed}] End of stream detected.")
            GLib.timeout_add_seconds(3, self._restart_video_feed, feed)
        elif message.type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure is not None and structure.get_name() == "GstMultiFileSink":
                filename = structure.get_value("filename") if structure.has_field("filename") else None
                if filename and self._should_log_preview_update(feed):
                    self._log(f"[{feed}] Preview updated: {filename}")
                if filename:
                    self._last_decoded_frame_at[feed] = time.time()
                    self._video_decode_missing_since.pop(feed, None)
        return True

    def _check_video_decode_health(self) -> bool:
        if not self._running:
            return False
        if self._packet_monitor is None:
            return True

        now = time.time()
        packet_activity = self._packet_monitor.snapshot()
        for feed, feed_state in list(self._video_feeds.items()):
            packet_state = packet_activity.get(feed) or {}
            if not bool(packet_state.get("receiving")):
                self._video_decode_missing_since.pop(feed, None)
                continue

            preview = describe_latest_preview(self._preview_dir, feed_state.preview_pattern)
            if preview.get("available"):
                self._last_decoded_frame_at[feed] = float(preview.get("updated_at_ts") or now)
                self._video_decode_missing_since.pop(feed, None)
                continue

            missing_since = self._video_decode_missing_since.setdefault(feed, now)
            missing_for = now - missing_since
            if missing_for < PACKETS_WITHOUT_DECODE_WARNING_SECONDS:
                continue

            last_restart = self._last_no_decode_restart_at.get(feed, 0.0)
            if now - last_restart < PACKETS_WITHOUT_DECODE_RESTART_SECONDS:
                continue

            self._last_no_decode_restart_at[feed] = now
            self._log(
                f"[{feed}] UDP/SRT packets are arriving but no decodable video preview has appeared for "
                f"{int(missing_for)}s; restarting video pipeline."
            )
            self._restart_video_feed(feed)
        return True

    def _start_recording_on_loop(self) -> None:
        if not self._running:
            raise RuntimeError("Server runtime is not running.")
        if self._recording_active:
            return

        recording_config = _resolve_recording_config(_load_config(self._config_path))

        timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        files = {
            "tn": RecordingPaths(
                temp_path=self._recording_dir / f"video_tn_{timestamp}.recording.mp4",
                final_path=self._archive_dir / f"video_tn_{timestamp}.mp4",
                failed_path=self._archive_dir / f"video_tn_{timestamp}.failed.mp4",
            ),
            "dk": RecordingPaths(
                temp_path=self._recording_dir / f"video_dk_{timestamp}.recording.mp4",
                final_path=self._archive_dir / f"video_dk_{timestamp}.mp4",
                failed_path=self._archive_dir / f"video_dk_{timestamp}.failed.mp4",
            ),
        }

        armed_feed_states: list[VideoFeedState] = []
        try:
            for feed, paths in files.items():
                feed_state = self._video_feeds.get(feed)
                if feed_state is None:
                    continue
                self._arm_recording_session(feed_state, paths, recording_config)
                self._attach_recording_probe(feed_state)
                armed_feed_states.append(feed_state)
        except Exception:
            for feed_state in armed_feed_states:
                self._detach_recording_probe(feed_state)
                if feed_state.recording_session is not None:
                    feed_state.recording_session.recorder.stop(timeout=5)
                    feed_state.recording_session = None
            raise

        with self._lock:
            self._recording_active = True
            self._recording_started_at = time.time()
            self._recording_files = files

        self._log("Recording armed for both feeds. Each MP4 will begin on the next IDR frame.")

    def _stop_recording_on_loop(self) -> None:
        if not self._running and not self._recording_active:
            return
        if not self._recording_active:
            return

        recording_sessions: dict[str, RecordingSession] = {}
        for feed_state in self._video_feeds.values():
            self._detach_recording_probe(feed_state)
            if feed_state.recording_session is not None:
                recording_sessions[feed_state.feed] = feed_state.recording_session
                feed_state.recording_session = None

        with self._lock:
            self._recording_active = False
            self._recording_started_at = None
            self._recording_files = {}

        self._log("Recording stopped. Finalizing archive files in background...")
        self._start_recording_finalization_worker(recording_sessions)

    def _attach_recording_probe(self, feed_state: VideoFeedState) -> None:
        if feed_state.tee is None or feed_state.recording_session is None:
            return
        if feed_state.recording_session.probe_id is not None:
            return

        tee_sink_pad = feed_state.tee.get_static_pad("sink")
        if tee_sink_pad is None:
            raise RuntimeError(f"Could not access tee sink pad for {feed_state.feed}.")

        probe_id = tee_sink_pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self._push_recording_buffer,
            feed_state.feed,
        )
        feed_state.recording_session.tee_sink_pad = tee_sink_pad
        feed_state.recording_session.probe_id = probe_id

    def _arm_recording_session(
        self,
        feed_state: VideoFeedState,
        paths: RecordingPaths,
        recording_config: dict[str, Any],
    ) -> None:
        recorder = LiveMp4Recorder(
            feed=feed_state.feed,
            paths=paths,
            audio_bitrate=recording_config["audio_bitrate"],
            audio_rate=recording_config["audio_rate"],
            audio_channels=recording_config["audio_channels"],
            video_mode=recording_config["video_mode"],
            log_callback=self._log,
        )
        recorder.start()
        feed_state.recording_session = RecordingSession(recorder=recorder)

    def _detach_recording_probe(self, feed_state: VideoFeedState) -> None:
        session = feed_state.recording_session
        if session is None or session.tee_sink_pad is None or session.probe_id is None:
            return

        session.tee_sink_pad.remove_probe(session.probe_id)
        session.tee_sink_pad = None
        session.probe_id = None

    def _start_recording_finalization_worker(self, recording_sessions: dict[str, RecordingSession]) -> None:
        with self._lock:
            self._finalization_active_count += 1

        thread = threading.Thread(
            target=self._finalize_recordings_worker,
            args=(recording_sessions,),
            name="recording-finalizer",
            daemon=True,
        )
        thread.start()

    def _finalize_recordings_worker(self, recording_sessions: dict[str, RecordingSession]) -> None:
        try:
            for feed, session in recording_sessions.items():
                try:
                    session.recorder.stop()
                except Exception as exc:  # pragma: no cover - runtime only
                    self._log(f"[{feed}] ERROR: Recording finalization failed unexpectedly. {exc}")
            self._log("Recording finalization complete.")
        finally:
            with self._lock:
                self._finalization_active_count = max(0, self._finalization_active_count - 1)

    def _configure_bus(
        self,
        pipeline: Gst.Pipeline,
        label: str,
        handler: Callable[[Gst.Bus, Gst.Message], bool],
    ) -> None:
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", handler)
        self._log(f"[{label}] Pipeline configured.")

    def _set_pipeline_state(
        self,
        pipeline: Gst.Pipeline,
        target_state: Gst.State,
        label: str,
        timeout_seconds: float = 5.0,
        suppress_errors: bool = False,
        allow_pending: bool = False,
    ) -> None:
        state_change = pipeline.set_state(target_state)
        if state_change == Gst.StateChangeReturn.FAILURE:
            message = f"[{label}] Could not change pipeline state to {_state_label(target_state)}."
            if suppress_errors:
                self._log(message)
                return
            raise RuntimeError(message)

        timeout_ns = int(timeout_seconds * Gst.SECOND)
        result, current_state, pending_state = pipeline.get_state(timeout_ns)
        if result == Gst.StateChangeReturn.FAILURE:
            message = f"[{label}] Pipeline failed while changing state to {_state_label(target_state)}."
            if suppress_errors:
                self._log(message)
                return
            raise RuntimeError(message)
        if allow_pending and target_state == Gst.State.PLAYING:
            if result in {Gst.StateChangeReturn.ASYNC, Gst.StateChangeReturn.NO_PREROLL}:
                self._log(f"[{label}] Pipeline armed and waiting for incoming stream data.")
                return
            if pending_state == target_state:
                self._log(f"[{label}] Pipeline armed and waiting to complete PLAYING on first packets.")
                return
        if result == Gst.StateChangeReturn.ASYNC:
            message = (
                f"[{label}] Timed out while waiting for pipeline state {_state_label(target_state)}; "
                f"current={_state_label(current_state)}, pending={_state_label(pending_state)}."
            )
            if suppress_errors:
                self._log(message)
                return
            raise RuntimeError(message)
        if current_state != target_state:
            message = (
                f"[{label}] Pipeline reached unexpected state {_state_label(current_state)} "
                f"while targeting {_state_label(target_state)}."
            )
            if suppress_errors:
                self._log(message)
                return
            raise RuntimeError(message)

    def _preview_snapshot(
        self,
        feed: str,
        pattern: str,
        packet_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if packet_state is not None and not bool(packet_state.get("receiving")):
            return {
                "available": False,
                "path": None,
                "updated_at": None,
                "updated_at_ts": None,
                "age_seconds": None,
                "health": {
                    "state": "no_packets",
                    "message": None,
                },
            }
        preview = describe_latest_preview(self._preview_dir, pattern)
        health: dict[str, Any] = {
            "state": "ok" if preview.get("available") else "waiting_for_video",
            "message": None,
        }
        if packet_state is not None and bool(packet_state.get("receiving")) and not preview.get("available"):
            missing_since = self._video_decode_missing_since.get(feed)
            missing_for = int(max(0.0, time.time() - missing_since)) if missing_since is not None else 0
            if missing_for >= PACKETS_WITHOUT_DECODE_WARNING_SECONDS:
                health = {
                    "state": "packets_without_decodable_video",
                    "message": f"UDP/SRT packets incoming, but no decodable video frame yet ({missing_for}s).",
                    "missing_for_seconds": missing_for,
                }
        preview["health"] = health
        return preview

    def _configure_audio_diagnostics(self, pipeline: Gst.Pipeline) -> None:
        self._audio_diagnostic_counts = {name: 0 for name in AUDIO_DIAGNOSTIC_ELEMENTS}
        self._last_audio_diagnostic_counts = dict(self._audio_diagnostic_counts)
        for element_name in AUDIO_DIAGNOSTIC_ELEMENTS:
            element = pipeline.get_by_name(element_name)
            if element is None:
                continue
            element.connect("handoff", self._on_audio_diagnostic_handoff, element_name)

    def _on_audio_diagnostic_handoff(self, _identity: Gst.Element, _buffer: Gst.Buffer, element_name: str) -> None:
        self._audio_diagnostic_counts[element_name] = self._audio_diagnostic_counts.get(element_name, 0) + 1

    def _log_audio_diagnostics(self) -> bool:
        if not self._running or self._audio_pipeline is None:
            return False
        parts = []
        for element_name, label in AUDIO_DIAGNOSTIC_ELEMENTS.items():
            current = self._audio_diagnostic_counts.get(element_name, 0)
            previous = self._last_audio_diagnostic_counts.get(element_name, 0)
            delta = current - previous
            state = "active" if delta > 0 else "inactive"
            parts.append(f"{label}: {state} (+{delta}, total={current})")
        self._last_audio_diagnostic_counts = dict(self._audio_diagnostic_counts)
        self._log("[audio] Path health: " + "; ".join(parts))
        return True

    def _build_audio_pipeline(self, config: dict[str, Any]) -> Gst.Pipeline:
        return Gst.parse_launch(build_audio_relay_pipeline_string(config))

    def _build_video_pipeline(self, feed_state: VideoFeedState) -> Gst.Pipeline:
        config = _load_config(self._config_path)
        video_streaming_settings = str(config.get("streaming_settings_video", "") or "").strip()
        video_srt_suffix = f"&{video_streaming_settings}" if video_streaming_settings else ""
        relay_input_queue = build_queue_element(
            config,
            ("server", "relay_input"),
            {
                "max_size_buffers": 120,
                "max_size_bytes": 0,
                "max_size_time_ms": 150,
            },
        )
        relay_output_queue = build_queue_element(
            config,
            ("server", "relay_output"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 100,
            },
        )
        preview_branch_queue = build_queue_element(
            config,
            ("server", "preview_branch"),
            {
                "max_size_buffers": 120,
                "max_size_bytes": 0,
                "max_size_time_ms": 0,
            },
        )
        preview_demux_queue = build_queue_element(
            config,
            ("server", "preview_demux"),
            {
                "max_size_buffers": 60,
                "max_size_bytes": 0,
                "max_size_time_ms": 0,
            },
        )
        preview_output_queue = build_queue_element(
            config,
            ("server", "preview_output"),
            {
                "leaky": "downstream",
                "max_size_buffers": 5,
                "max_size_bytes": 0,
                "max_size_time_ms": 0,
            },
        )
        pipeline_str = f"""
            srtsrc name={feed_state.feed}_source uri="srt://:{feed_state.send_port}?mode=listener{video_srt_suffix}" wait-for-connection=false !
            {relay_input_queue} !
            tsparse set-timestamps=true !
            tee name={feed_state.feed}_stream_tee

            {feed_state.feed}_stream_tee. ! {relay_output_queue} !
            srtsink name={feed_state.feed}_relay uri="srt://:{feed_state.receive_port}?mode=listener{video_srt_suffix}" wait-for-connection=false

            {feed_state.feed}_stream_tee. ! {preview_branch_queue} !
            tsdemux latency=50 name={feed_state.feed}_preview_demux
            {feed_state.feed}_preview_demux. ! {preview_demux_queue} ! h264parse name={feed_state.feed}_preview_h264parse config-interval=1 !
            avdec_h264 !
            {preview_output_queue} !
            videoconvert ! videoscale ! videorate drop-only=true !
            video/x-raw,width=640,height=360,framerate=1/5 !
            jpegenc quality=70 !
            multifilesink location="{feed_state.preview_pattern}" max-files=2 post-messages=true sync=false async=false
        """
        return Gst.parse_launch(pipeline_str.strip())

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)

    def _should_log_preview_update(self, feed: str) -> bool:
        now = time.monotonic()
        last_logged_at = self._last_preview_log_at.get(feed)
        if last_logged_at is not None and (now - last_logged_at) < 5:
            return False
        self._last_preview_log_at[feed] = now
        return True

    def _throttle_preview_h264(
        self,
        pad: Gst.Pad,
        info: Gst.PadProbeInfo,
        feed: str,
    ) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        if buffer.has_flags(Gst.BufferFlags.DELTA_UNIT):
            return Gst.PadProbeReturn.DROP

        now = time.monotonic()
        next_allowed_at = self._next_preview_frame_at.get(feed, 0.0)
        if now < next_allowed_at:
            return Gst.PadProbeReturn.DROP

        self._next_preview_frame_at[feed] = now + PREVIEW_FRAME_INTERVAL_SECONDS
        return Gst.PadProbeReturn.OK

    def _push_recording_buffer(
        self,
        pad: Gst.Pad,
        info: Gst.PadProbeInfo,
        feed: str,
    ) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        feed_state = self._video_feeds.get(feed)
        if feed_state is None or feed_state.recording_session is None:
            return Gst.PadProbeReturn.OK

        feed_state.recording_session.recorder.push_ts_buffer(buffer)
        return Gst.PadProbeReturn.OK


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise RuntimeError("Config must be a top-level YAML mapping.")
    return data


def build_audio_relay_pipeline_string(config: dict[str, Any]) -> str:
    ports = config.get("ports", {})
    audio = config.get("audio", {})
    audio_rate = int(audio.get("rate", 48000))
    channels = int(audio.get("channels", 2))
    encoding_name = str(audio.get("encoding_name", "L16")).strip() or "L16"
    audio_format = str(audio.get("format", "S16BE")).strip().upper() or "S16BE"
    audio_streaming_settings = str(config.get("streaming_settings_audio", "") or "").strip()
    audio_srt_suffix = f"&{audio_streaming_settings}" if audio_streaming_settings else ""
    if audio_format != "S16BE":
        raise RuntimeError("audio.format must be S16BE for the separate RTP L16 relay pipeline.")
    audio_input_queue = build_queue_element(
        config,
        ("server", "audio_input"),
        {
            "max_size_buffers": 30,
            "max_size_bytes": 0,
            "max_size_time_ms": 75,
        },
    )
    audio_output_queue = build_queue_element(
        config,
        ("server", "audio_output"),
        {
            "max_size_buffers": 30,
            "max_size_bytes": 0,
            "max_size_time_ms": 75,
        },
    )

    pipeline_str = f"""
        srtsrc name=a_send_tn uri=srt://:{ports["audio_send_tn"]}?mode=listener{audio_srt_suffix} wait-for-connection=false !
          {audio_input_queue} !
          application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          identity name=audio_diag_tn_uplink signal-handoffs=true silent=true !
          tee name=tee_tn

        srtsrc name=a_send_dk uri=srt://:{ports["audio_send_dk"]}?mode=listener{audio_srt_suffix} wait-for-connection=false !
          {audio_input_queue} !
          application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          identity name=audio_diag_dk_uplink signal-handoffs=true silent=true !
          tee name=tee_dk

        tee_tn. ! {audio_output_queue} !
          audioconvert ! audioresample !
          audio/x-raw,format=S16BE,layout=interleaved,channels={channels},rate={audio_rate} !
          identity name=audio_diag_tn_to_dk_return signal-handoffs=true silent=true !
          rtpL16pay !
          srtsink name=a_recv_dk uri=srt://:{ports["audio_receive_dk"]}?mode=listener{audio_srt_suffix} wait-for-connection=false

        tee_dk. ! {audio_output_queue} !
          audioconvert ! audioresample !
          audio/x-raw,format=S16BE,layout=interleaved,channels={channels},rate={audio_rate} !
          identity name=audio_diag_dk_to_tn_return signal-handoffs=true silent=true !
          rtpL16pay !
          srtsink name=a_recv_tn uri=srt://:{ports["audio_receive_tn"]}?mode=listener{audio_srt_suffix} wait-for-connection=false
    """
    return pipeline_str.strip()


def _resolve_recording_config(config: dict[str, Any]) -> dict[str, Any]:
    audio = config.get("audio", {})
    recording = config.get("recording", {})
    recording_audio = recording.get("audio", {}) if isinstance(recording.get("audio", {}), dict) else {}
    recording_video = recording.get("video", {}) if isinstance(recording.get("video", {}), dict) else {}

    audio_rate = int(audio.get("rate", 48000))
    audio_channels = int(audio.get("channels", 2))
    audio_bitrate = int(recording_audio.get("bitrate", audio.get("aac_bitrate", 128000)))
    video_mode = str(recording_video.get("mode", "copy")).strip().lower() or "copy"
    if video_mode != "copy":
        raise RuntimeError("recording.video.mode currently supports only 'copy'.")

    audio_codec = str(recording_audio.get("codec", "aac")).strip().lower() or "aac"
    if audio_codec != "aac":
        raise RuntimeError("recording.audio.codec currently supports only 'aac'.")

    return {
        "audio_bitrate": audio_bitrate,
        "audio_rate": audio_rate,
        "audio_channels": audio_channels,
        "video_mode": video_mode,
    }


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _state_label(state: Gst.State) -> str:
    try:
        return Gst.Element.state_get_name(state)
    except Exception:
        return str(state)
