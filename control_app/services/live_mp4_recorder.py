from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)


@dataclass(frozen=True)
class RecordingPaths:
    temp_path: Path
    final_path: Path
    failed_path: Path


class LiveMp4Recorder:
    def __init__(
        self,
        feed: str,
        paths: RecordingPaths,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._feed = feed
        self._paths = paths
        self._log_callback = log_callback

        self._lock = threading.Lock()
        self._pipeline: Gst.Pipeline | None = None
        self._appsrc: Gst.Element | None = None
        self._demux: Gst.Element | None = None
        self._mux: Gst.Element | None = None
        self._bus_thread: threading.Thread | None = None
        self._finished = threading.Event()
        self._accepting_data = False
        self._start_pts_ns: int | None = None
        self._error_message: str | None = None
        self._logged_push_failure = False
        self._logged_missing_h264_timestamper = False
        self._audio_branch_linked = False
        self._video_branch_linked = False

    @property
    def temp_path(self) -> Path:
        return self._paths.temp_path

    def start(self) -> None:
        self._paths.temp_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_unlink(self._paths.temp_path)
        _safe_unlink(self._paths.failed_path)

        pipeline = Gst.Pipeline.new(f"{self._feed}_mp4_recording")
        appsrc = Gst.ElementFactory.make("appsrc", f"{self._feed}_record_source")
        source_queue = Gst.ElementFactory.make("queue", f"{self._feed}_record_source_queue")
        tsparse = Gst.ElementFactory.make("tsparse", f"{self._feed}_record_tsparse")
        demux = Gst.ElementFactory.make("tsdemux", f"{self._feed}_record_demux")
        mux = Gst.ElementFactory.make("mp4mux", f"{self._feed}_record_mux")
        sink = Gst.ElementFactory.make("filesink", f"{self._feed}_record_sink")

        if any(element is None for element in (pipeline, appsrc, source_queue, tsparse, demux, mux, sink)):
            raise RuntimeError(f"Could not create MP4 recording pipeline for {self._feed}.")

        appsrc.set_property(
            "caps",
            Gst.Caps.from_string("video/mpegts, systemstream=(boolean)true, packetsize=(int)188"),
        )
        appsrc.set_property("is-live", True)
        appsrc.set_property("format", Gst.Format.TIME)
        appsrc.set_property("block", False)
        tsparse.set_property("set-timestamps", True)
        sink.set_property("location", str(self._paths.temp_path))
        sink.set_property("sync", False)
        sink.set_property("async", False)

        pipeline.add(appsrc)
        pipeline.add(source_queue)
        pipeline.add(tsparse)
        pipeline.add(demux)
        pipeline.add(mux)
        pipeline.add(sink)

        if not appsrc.link(source_queue):
            raise RuntimeError(f"Could not link appsrc for {self._feed} recording.")
        if not source_queue.link(tsparse):
            raise RuntimeError(f"Could not link tsparse source queue for {self._feed} recording.")
        if not tsparse.link(demux):
            raise RuntimeError(f"Could not link tsparse to demux for {self._feed} recording.")
        if not mux.link(sink):
            raise RuntimeError(f"Could not link mp4mux to filesink for {self._feed} recording.")

        with self._lock:
            self._pipeline = pipeline
            self._appsrc = appsrc
            self._demux = demux
            self._mux = mux
            self._accepting_data = True
            self._finished.clear()
            self._error_message = None
            self._start_pts_ns = None
            self._logged_push_failure = False
            self._audio_branch_linked = False
            self._video_branch_linked = False

        demux.connect("pad-added", self._on_demux_pad_added)

        state_change = pipeline.set_state(Gst.State.PLAYING)
        if state_change == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            with self._lock:
                self._pipeline = None
                self._appsrc = None
                self._demux = None
                self._mux = None
                self._accepting_data = False
            raise RuntimeError(f"Could not start MP4 recording pipeline for {self._feed}.")

        bus_thread = threading.Thread(
            target=self._watch_bus,
            name=f"{self._feed}-mp4-recording-bus",
            daemon=True,
        )
        bus_thread.start()
        with self._lock:
            self._bus_thread = bus_thread

        self._log(f"[{self._feed}] MP4 recorder armed. Waiting for next IDR frame before writing A/V.")

    def push_ts_buffer(self, buffer: Gst.Buffer) -> None:
        with self._lock:
            if not self._accepting_data or self._appsrc is None:
                return
            appsrc = self._appsrc

        flow = appsrc.emit("push-buffer", buffer.copy_deep())
        if flow == Gst.FlowReturn.OK:
            return

        if flow != Gst.FlowReturn.FLUSHING and not self._logged_push_failure:
            with self._lock:
                if self._logged_push_failure:
                    return
                self._logged_push_failure = True
            flow_label = getattr(flow, "value_nick", str(int(flow)))
            self._log(f"[{self._feed}] WARNING: MP4 recorder dropped TS data ({flow_label}).")

    def stop(self, timeout: float = 30.0) -> None:
        with self._lock:
            self._accepting_data = False
            appsrc = self._appsrc
            pipeline = self._pipeline

        if appsrc is not None:
            appsrc.emit("end-of-stream")

        finished = self._finished.wait(timeout=timeout)
        if not finished:
            with self._lock:
                if self._error_message is None:
                    self._error_message = "Timed out while finalizing MP4 recording."
            self._finished.set()
            self._log(f"[{self._feed}] ERROR: Timed out while waiting for MP4 finalization.")

        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)

        with self._lock:
            bus_thread = self._bus_thread
            start_pts_ns = self._start_pts_ns
            error_message = self._error_message
            self._pipeline = None
            self._appsrc = None
            self._demux = None
            self._mux = None
            self._bus_thread = None

        if bus_thread is not None:
            bus_thread.join(timeout=2)

        if error_message is not None:
            self._preserve_failed_recording()
            return

        if start_pts_ns is None:
            _safe_unlink(self._paths.temp_path)
            self._log(f"[{self._feed}] Recording stopped before the next IDR frame; no MP4 was written.")
            return

        if not self._paths.temp_path.exists() or self._paths.temp_path.stat().st_size == 0:
            _safe_unlink(self._paths.temp_path)
            self._log(f"[{self._feed}] Recording produced no MP4 output.")
            return

        _safe_unlink(self._paths.final_path)
        self._paths.temp_path.replace(self._paths.final_path)
        self._log(f"[{self._feed}] Final archive ready: {self._paths.final_path}")

    def _watch_bus(self) -> None:
        with self._lock:
            pipeline = self._pipeline
        if pipeline is None:
            return

        bus = pipeline.get_bus()
        while True:
            message = bus.timed_pop_filtered(
                Gst.SECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is None:
                if self._finished.is_set():
                    return
                continue

            if message.type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                with self._lock:
                    if self._error_message is None:
                        self._error_message = f"{err}. {debug or ''}".strip()
                    self._accepting_data = False
                self._log(f"[{self._feed}] ERROR: MP4 recorder failed. {err}. {debug or ''}".strip())
                self._finished.set()
                return

            if message.type == Gst.MessageType.EOS:
                self._finished.set()
                return

    def _on_demux_pad_added(self, demux: Gst.Element, pad: Gst.Pad) -> None:
        try:
            caps = pad.get_current_caps() or pad.query_caps(None)
            if caps is None or caps.get_size() == 0:
                return

            structure = caps.get_structure(0)
            media_type = structure.get_name()
            if media_type.startswith("video/"):
                self._attach_video_branch(pad)
                return
            if media_type == "audio/mpeg":
                self._attach_audio_branch(pad)
        except Exception as exc:  # pragma: no cover - runtime only
            with self._lock:
                if self._error_message is None:
                    self._error_message = str(exc)
                self._accepting_data = False
            self._log(f"[{self._feed}] ERROR: Could not attach recorder branch. {exc}")
            self._finished.set()

    def _attach_video_branch(self, pad: Gst.Pad) -> None:
        with self._lock:
            if self._video_branch_linked or self._pipeline is None or self._mux is None:
                return
            pipeline = self._pipeline
            mux = self._mux
            self._video_branch_linked = True

        queue = _make_element("queue", f"{self._feed}_record_video_queue")
        parser = _make_element("h264parse", f"{self._feed}_record_h264parse")
        parser.set_property("config-interval", 1)

        elements = [queue, parser]
        tail = parser
        if Gst.ElementFactory.find("h264timestamper") is not None:
            timestamper = _make_element("h264timestamper", f"{self._feed}_record_h264timestamper")
            elements.append(timestamper)
            tail = timestamper
        elif not self._logged_missing_h264_timestamper:
            self._logged_missing_h264_timestamper = True
            self._log(f"[{self._feed}] WARNING: h264timestamper is unavailable; recording without it.")

        _add_and_link_elements(pipeline, elements)

        sink_pad = queue.get_static_pad("sink")
        if sink_pad is None or pad.link(sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link video demux pad for {self._feed} recording.")

        src_pad = tail.get_static_pad("src")
        if src_pad is None:
            raise RuntimeError(f"Could not access video recorder src pad for {self._feed}.")
        src_pad.add_probe(Gst.PadProbeType.BUFFER, self._video_gate_probe)

        mux_pad = _request_mux_pad(mux, "video")
        if src_pad.link(mux_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link video branch to MP4 mux for {self._feed}.")

        _sync_elements_with_parent(elements)

    def _attach_audio_branch(self, pad: Gst.Pad) -> None:
        with self._lock:
            if self._audio_branch_linked or self._pipeline is None or self._mux is None:
                return
            pipeline = self._pipeline
            mux = self._mux
            self._audio_branch_linked = True

        queue = _make_element("queue", f"{self._feed}_record_audio_queue")
        parser = _make_element("aacparse", f"{self._feed}_record_aacparse")
        elements = [queue, parser]

        _add_and_link_elements(pipeline, elements)

        sink_pad = queue.get_static_pad("sink")
        if sink_pad is None or pad.link(sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link audio demux pad for {self._feed} recording.")

        src_pad = parser.get_static_pad("src")
        if src_pad is None:
            raise RuntimeError(f"Could not access audio recorder src pad for {self._feed}.")
        src_pad.add_probe(Gst.PadProbeType.BUFFER, self._audio_gate_probe)

        mux_pad = _request_mux_pad(mux, "audio")
        if src_pad.link(mux_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link audio branch to MP4 mux for {self._feed}.")

        _sync_elements_with_parent(elements)

    def _video_gate_probe(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        timestamp_ns = _buffer_timestamp_ns(buffer)
        if timestamp_ns is None:
            return Gst.PadProbeReturn.DROP

        with self._lock:
            start_pts_ns = self._start_pts_ns

        if start_pts_ns is None:
            if not _is_idr_candidate(buffer):
                return Gst.PadProbeReturn.DROP

            with self._lock:
                if self._start_pts_ns is None:
                    self._start_pts_ns = timestamp_ns
                    self._log(
                        f"[{self._feed}] MP4 recording aligned on IDR at {timestamp_ns / Gst.SECOND:.3f}s."
                    )
            return Gst.PadProbeReturn.OK

        if timestamp_ns < start_pts_ns:
            return Gst.PadProbeReturn.DROP
        return Gst.PadProbeReturn.OK

    def _audio_gate_probe(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        timestamp_ns = _buffer_timestamp_ns(buffer)
        if timestamp_ns is None:
            return Gst.PadProbeReturn.DROP

        with self._lock:
            start_pts_ns = self._start_pts_ns

        if start_pts_ns is None or timestamp_ns < start_pts_ns:
            return Gst.PadProbeReturn.DROP
        return Gst.PadProbeReturn.OK

    def _preserve_failed_recording(self) -> None:
        if not self._paths.temp_path.exists():
            return
        _safe_unlink(self._paths.failed_path)
        self._paths.temp_path.replace(self._paths.failed_path)
        self._log(f"[{self._feed}] Preserved failed MP4 artifact: {self._paths.failed_path}")

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)


def _make_element(factory: str, name: str) -> Gst.Element:
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"Could not create GStreamer element: {factory}")
    return element


def _add_and_link_elements(pipeline: Gst.Pipeline, elements: list[Gst.Element]) -> None:
    for element in elements:
        pipeline.add(element)
    for upstream, downstream in zip(elements, elements[1:]):
        if not upstream.link(downstream):
            raise RuntimeError(f"Could not link {upstream.get_name()} -> {downstream.get_name()}.")


def _sync_elements_with_parent(elements: list[Gst.Element]) -> None:
    for element in elements:
        element.sync_state_with_parent()


def _request_mux_pad(mux: Gst.Element, media_type: str) -> Gst.Pad:
    for template in (f"{media_type}_%u", f"{media_type}_0"):
        pad = mux.get_request_pad(template)
        if pad is not None:
            return pad

    raise RuntimeError(f"Could not allocate {media_type} pad on MP4 mux.")


def _buffer_timestamp_ns(buffer: Gst.Buffer) -> int | None:
    if buffer.pts != Gst.CLOCK_TIME_NONE:
        return int(buffer.pts)
    if buffer.dts != Gst.CLOCK_TIME_NONE:
        return int(buffer.dts)
    return None


def _is_idr_candidate(buffer: Gst.Buffer) -> bool:
    flags = buffer.get_flags()
    if flags & Gst.BufferFlags.DELTA_UNIT:
        return False
    if flags & Gst.BufferFlags.HEADER:
        return False
    return True


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
