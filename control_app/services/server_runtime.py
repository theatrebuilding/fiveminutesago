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

from .live_mp4_recorder import LiveMp4Recorder, RecordingPaths
from .preview_catalog import build_server_preview_pattern, describe_latest_preview, prune_preview_files


Gst.init(None)


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
            previews = {
                feed: describe_latest_preview(self._preview_dir, feed_state.preview_pattern)
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

        self._audio_pipeline = self._build_audio_pipeline(config)
        self._configure_bus(self._audio_pipeline, "audio", self._on_audio_message)
        self._audio_pipeline.set_state(Gst.State.PLAYING)

        self._last_preview_log_at = {}
        self._last_continuity_warning_at = {}

        for feed in self._video_feeds.values():
            self._start_video_feed(feed)

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
                feed_state.pipeline.set_state(Gst.State.NULL)
                feed_state.pipeline = None
                feed_state.tee = None
                feed_state.recording_session = None

        if self._audio_pipeline is not None:
            self._audio_pipeline.set_state(Gst.State.NULL)
            self._audio_pipeline = None

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
        pipeline.set_state(Gst.State.PLAYING)
        if self._recording_active:
            record_paths = self._recording_files.get(feed_state.feed)
            if record_paths is not None:
                if feed_state.recording_session is None:
                    self._arm_recording_session(feed_state, record_paths)
                self._attach_recording_probe(feed_state)

    def _restart_video_feed(self, feed: str) -> bool:
        if not self._running:
            return False
        feed_state = self._video_feeds[feed]
        self._log(f"[{feed}] Restarting video pipeline.")

        if feed_state.pipeline is not None:
            self._detach_recording_probe(feed_state)
            feed_state.pipeline.set_state(Gst.State.NULL)
            feed_state.pipeline = None
            feed_state.tee = None

        self._start_video_feed(feed_state)
        return False

    def _restart_audio_pipeline(self) -> bool:
        if not self._running:
            return False
        config = _load_config(self._config_path)
        self._log("[audio] Restarting audio pipeline.")

        if self._audio_pipeline is not None:
            self._audio_pipeline.set_state(Gst.State.NULL)

        self._audio_pipeline = self._build_audio_pipeline(config)
        self._configure_bus(self._audio_pipeline, "audio", self._on_audio_message)
        self._audio_pipeline.set_state(Gst.State.PLAYING)
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
        return True

    def _start_recording_on_loop(self) -> None:
        if not self._running:
            raise RuntimeError("Server runtime is not running.")
        if self._recording_active:
            return

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
                self._arm_recording_session(feed_state, paths)
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

    def _arm_recording_session(self, feed_state: VideoFeedState, paths: RecordingPaths) -> None:
        recorder = LiveMp4Recorder(
            feed=feed_state.feed,
            paths=paths,
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

    def _build_audio_pipeline(self, config: dict[str, Any]) -> Gst.Pipeline:
        ports = config.get("ports", {})
        audio = config.get("audio", {})

        pipeline_str = f"""
            srtsrc name=a_send_tn uri=srt://:{ports["audio_send_tn"]}?mode=listener wait-for-connection=false !
              queue !
              application/x-rtp,media=audio,clock-rate={audio.get("rate", 32000)},encoding-name={audio.get("encoding_name", "L16")},channels={audio.get("channels", 2)} !
              rtpL16depay !
              tee name=tee_tn

            srtsrc name=a_send_dk uri=srt://:{ports["audio_send_dk"]}?mode=listener wait-for-connection=false !
              queue !
              application/x-rtp,media=audio,clock-rate={audio.get("rate", 32000)},encoding-name={audio.get("encoding_name", "L16")},channels={audio.get("channels", 2)} !
              rtpL16depay !
              tee name=tee_dk

            tee_tn. ! queue !
              audioconvert ! audioresample !
              audio/x-raw,format={audio.get("format", "S16BE")},channels={audio.get("channels", 2)},rate={audio.get("rate", 32000)} !
              rtpL16pay !
              srtsink name=a_recv_dk uri=srt://:{ports["audio_receive_dk"]}?mode=listener wait-for-connection=false

            tee_dk. ! queue !
              audioconvert ! audioresample !
              audio/x-raw,format={audio.get("format", "S16BE")},channels={audio.get("channels", 2)},rate={audio.get("rate", 32000)} !
              rtpL16pay !
              srtsink name=a_recv_tn uri=srt://:{ports["audio_receive_tn"]}?mode=listener wait-for-connection=false
        """
        return Gst.parse_launch(pipeline_str.strip())

    def _build_video_pipeline(self, feed_state: VideoFeedState) -> Gst.Pipeline:
        pipeline_str = f"""
            srtsrc name={feed_state.feed}_source uri="srt://:{feed_state.send_port}?mode=listener" wait-for-connection=false !
            queue max-size-time=5000000000 max-size-buffers=500 !
            tsparse set-timestamps=true !
            tee name={feed_state.feed}_stream_tee

            {feed_state.feed}_stream_tee. ! queue !
            srtsink name={feed_state.feed}_relay uri="srt://:{feed_state.receive_port}?mode=listener" wait-for-connection=false

            {feed_state.feed}_stream_tee. ! queue max-size-buffers=120 max-size-bytes=0 max-size-time=0 !
            tsdemux name={feed_state.feed}_preview_demux
            {feed_state.feed}_preview_demux. ! queue max-size-buffers=60 max-size-bytes=0 max-size-time=0 ! h264parse config-interval=1 !
            avdec_h264 !
            queue leaky=downstream max-size-buffers=5 max-size-bytes=0 max-size-time=0 !
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


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
