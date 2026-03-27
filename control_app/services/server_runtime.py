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

from .preview_catalog import build_server_preview_pattern, describe_latest_preview


Gst.init(None)


@dataclass
class RecordingBranch:
    tee_pad: Gst.Pad
    queue: Gst.Element
    sink: Gst.Element
    path: Path


@dataclass
class VideoFeedState:
    feed: str
    send_port: int
    receive_port: int
    preview_pattern: str
    pipeline: Gst.Pipeline | None = None
    tee: Gst.Element | None = None
    recording_branch: RecordingBranch | None = None


class ServerRuntime:
    def __init__(
        self,
        config_path: Path,
        archive_dir: Path,
        preview_dir: Path,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._config_path = config_path
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
        self._recording_files: dict[str, Path] = {}
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._last_exit_code: int | None = None
        self._running = False

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

        self._run_on_loop(self._stop_runtime)

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
        self._run_on_loop(self._stop_recording_on_loop)
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
                    "started_at": _to_iso(self._recording_started_at),
                    "started_at_ts": self._recording_started_at,
                    "files": {
                        feed: str(path) for feed, path in self._recording_files.items()
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

    def _run_on_loop(self, func: Callable[[], Any]) -> Any:
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
        if not done.wait(timeout=20):
            raise RuntimeError("Server runtime operation timed out.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _start_runtime(self) -> None:
        config = _load_config(self._config_path)
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

        self._audio_pipeline = self._build_audio_pipeline(config)
        self._configure_bus(self._audio_pipeline, "audio", self._on_audio_message)
        self._audio_pipeline.set_state(Gst.State.PLAYING)

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
                feed_state.pipeline.set_state(Gst.State.NULL)
                feed_state.pipeline = None
                feed_state.tee = None
                feed_state.recording_branch = None

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
            record_path = self._recording_files.get(feed_state.feed)
            if record_path is not None:
                self._attach_recording_branch(feed_state, record_path, append=True)

    def _restart_video_feed(self, feed: str) -> bool:
        if not self._running:
            return False
        feed_state = self._video_feeds[feed]
        self._log(f"[{feed}] Restarting video pipeline.")

        if feed_state.pipeline is not None:
            feed_state.pipeline.set_state(Gst.State.NULL)
            feed_state.pipeline = None
            feed_state.tee = None
            feed_state.recording_branch = None

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
        elif message.type == Gst.MessageType.EOS:
            self._log(f"[{feed}] End of stream detected.")
            GLib.timeout_add_seconds(3, self._restart_video_feed, feed)
        return True

    def _start_recording_on_loop(self) -> None:
        if not self._running:
            raise RuntimeError("Server runtime is not running.")
        if self._recording_active:
            return

        timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        files = {
            "tn": self._archive_dir / f"video_tn_{timestamp}.ts",
            "dk": self._archive_dir / f"video_dk_{timestamp}.ts",
        }

        for feed, path in files.items():
            feed_state = self._video_feeds.get(feed)
            if feed_state is not None:
                self._attach_recording_branch(feed_state, path, append=False)

        with self._lock:
            self._recording_active = True
            self._recording_started_at = time.time()
            self._recording_files = files

        self._log("Recording started for both feeds.")

    def _stop_recording_on_loop(self) -> None:
        if not self._running and not self._recording_active:
            return
        if not self._recording_active:
            return

        for feed_state in self._video_feeds.values():
            self._detach_recording_branch(feed_state)

        with self._lock:
            self._recording_active = False
            self._recording_started_at = None
            self._recording_files = {}

        self._log("Recording stopped for both feeds.")

    def _attach_recording_branch(self, feed_state: VideoFeedState, path: Path, append: bool) -> None:
        if feed_state.pipeline is None or feed_state.tee is None:
            return
        if feed_state.recording_branch is not None:
            return

        queue = Gst.ElementFactory.make("queue", f"{feed_state.feed}_record_queue")
        sink = Gst.ElementFactory.make("filesink", f"{feed_state.feed}_record_sink")
        if queue is None or sink is None:
            raise RuntimeError(f"Could not create recording branch for {feed_state.feed}.")

        sink.set_property("location", str(path))
        sink.set_property("append", append)

        feed_state.pipeline.add(queue)
        feed_state.pipeline.add(sink)

        if not queue.link(sink):
            raise RuntimeError(f"Could not link recording sink for {feed_state.feed}.")

        tee_pad = feed_state.tee.get_request_pad("src_%u")
        if tee_pad is None:
            raise RuntimeError(f"Could not allocate tee pad for {feed_state.feed}.")

        queue_pad = queue.get_static_pad("sink")
        if queue_pad is None or tee_pad.link(queue_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link recording branch for {feed_state.feed}.")

        queue.sync_state_with_parent()
        sink.sync_state_with_parent()

        feed_state.recording_branch = RecordingBranch(
            tee_pad=tee_pad,
            queue=queue,
            sink=sink,
            path=path,
        )

    def _detach_recording_branch(self, feed_state: VideoFeedState) -> None:
        branch = feed_state.recording_branch
        if feed_state.pipeline is None or branch is None:
            return

        queue_pad = branch.queue.get_static_pad("sink")
        if queue_pad is not None:
            branch.tee_pad.unlink(queue_pad)
        if feed_state.tee is not None:
            feed_state.tee.release_request_pad(branch.tee_pad)

        branch.sink.set_state(Gst.State.NULL)
        branch.queue.set_state(Gst.State.NULL)
        feed_state.pipeline.remove(branch.sink)
        feed_state.pipeline.remove(branch.queue)
        feed_state.recording_branch = None

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
            tee name={feed_state.feed}_stream_tee

            {feed_state.feed}_stream_tee. ! queue !
            srtsink name={feed_state.feed}_relay uri="srt://:{feed_state.receive_port}?mode=listener" wait-for-connection=false

            {feed_state.feed}_stream_tee. ! queue !
            tsdemux name={feed_state.feed}_preview_demux
            {feed_state.feed}_preview_demux. ! queue ! h264parse config-interval=1 !
            avdec_h264 !
            videoconvert ! videoscale ! videorate !
            video/x-raw,width=640,height=360,framerate=1/1 !
            jpegenc quality=70 !
            multifilesink location="{feed_state.preview_pattern}" max-files=2
        """
        return Gst.parse_launch(pipeline_str.strip())

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)


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
