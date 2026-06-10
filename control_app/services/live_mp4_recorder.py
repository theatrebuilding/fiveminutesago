from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
from typing import BinaryIO, Callable

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)


@dataclass(frozen=True)
class RecordingPaths:
    temp_path: Path
    final_path: Path
    failed_path: Path
    raw_temp_path: Path
    raw_final_path: Path
    audio_fallback_path: Path


class LiveMp4Recorder:
    def __init__(
        self,
        feed: str,
        paths: RecordingPaths,
        audio_bitrate: int = 128000,
        audio_rate: int = 48000,
        audio_channels: int = 2,
        video_mode: str = "copy",
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._feed = feed
        self._paths = paths
        self._audio_bitrate = int(audio_bitrate)
        self._audio_rate = int(audio_rate)
        self._audio_channels = int(audio_channels)
        self._video_mode = str(video_mode).strip().lower() or "copy"
        self._log_callback = log_callback

        self._lock = threading.Lock()
        self._pipeline: Gst.Pipeline | None = None
        self._appsrc: Gst.Element | None = None
        self._demux: Gst.Element | None = None
        self._mux: Gst.Element | None = None
        self._bus_thread: threading.Thread | None = None
        self._raw_file: BinaryIO | None = None
        self._finished = threading.Event()
        self._accepting_data = False
        self._accepting_mp4_data = False
        self._start_pts_ns: int | None = None
        self._error_message: str | None = None
        self._logged_push_failure = False
        self._logged_raw_write_failure = False
        self._logged_missing_h264_timestamper = False
        self._audio_branch_linked = False
        self._video_branch_linked = False

    @property
    def temp_path(self) -> Path:
        return self._paths.temp_path

    def start(self) -> None:
        if self._video_mode != "copy":
            raise RuntimeError("Live MP4 recording currently supports only recording.video.mode=copy.")

        self._paths.temp_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.final_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.raw_temp_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_unlink(self._paths.temp_path)
        _safe_unlink(self._paths.failed_path)
        _safe_unlink(self._paths.raw_temp_path)
        _safe_unlink(self._paths.raw_final_path)
        _safe_unlink(self._paths.audio_fallback_path)

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

        raw_file = self._paths.raw_temp_path.open("wb")

        with self._lock:
            self._pipeline = pipeline
            self._appsrc = appsrc
            self._demux = demux
            self._mux = mux
            self._raw_file = raw_file
            self._accepting_data = True
            self._accepting_mp4_data = True
            self._finished.clear()
            self._error_message = None
            self._start_pts_ns = None
            self._logged_push_failure = False
            self._logged_raw_write_failure = False
            self._audio_branch_linked = False
            self._video_branch_linked = False

        demux.connect("pad-added", self._on_demux_pad_added)

        state_change = pipeline.set_state(Gst.State.PLAYING)
        if state_change == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            raw_file.close()
            with self._lock:
                self._pipeline = None
                self._appsrc = None
                self._demux = None
                self._mux = None
                self._raw_file = None
                self._accepting_data = False
                self._accepting_mp4_data = False
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
            if not self._accepting_data:
                return
            raw_file = self._raw_file
            appsrc = self._appsrc if self._accepting_mp4_data else None
            if raw_file is not None:
                try:
                    raw_file.write(_buffer_bytes(buffer))
                except Exception as exc:  # pragma: no cover - filesystem/runtime only
                    if not self._logged_raw_write_failure:
                        self._logged_raw_write_failure = True
                        self._log(f"[{self._feed}] WARNING: Could not write raw TS recording data. {exc}")

        if appsrc is None:
            return

        flow = appsrc.emit("push-buffer", buffer.copy_deep())
        if flow == Gst.FlowReturn.OK:
            return

        flow_label = _enum_label(flow)
        with self._lock:
            self._accepting_mp4_data = False
            if self._error_message is None:
                self._error_message = f"MP4 recorder push-buffer returned {flow_label}."

        if flow != Gst.FlowReturn.FLUSHING and not self._logged_push_failure:
            with self._lock:
                if self._logged_push_failure:
                    return
                self._logged_push_failure = True
            self._log(f"[{self._feed}] WARNING: MP4 recorder dropped TS data ({flow_label}).")

    def stop(self, timeout: float = 30.0) -> None:
        with self._lock:
            self._accepting_data = False
            self._accepting_mp4_data = False
            appsrc = self._appsrc
            pipeline = self._pipeline
            raw_file = self._raw_file
            self._raw_file = None

        if appsrc is not None:
            appsrc.emit("end-of-stream")

        if raw_file is not None:
            raw_file.close()

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
            self._finalize_with_raw_fallback(error_message)
            return

        if start_pts_ns is None:
            if self._has_raw_recording():
                self._finalize_with_raw_fallback("Recording stopped before the live MP4 muxer aligned on an IDR frame.")
            else:
                _safe_unlink(self._paths.temp_path)
                self._log(f"[{self._feed}] Recording stopped before the next IDR frame; no MP4 was written.")
            return

        if not self._paths.temp_path.exists() or self._paths.temp_path.stat().st_size == 0:
            _safe_unlink(self._paths.temp_path)
            if self._has_raw_recording():
                self._finalize_with_raw_fallback("Live MP4 muxer produced no output.")
            else:
                self._log(f"[{self._feed}] Recording produced no MP4 output.")
            return

        _safe_unlink(self._paths.final_path)
        self._paths.temp_path.replace(self._paths.final_path)
        _safe_unlink(self._paths.raw_temp_path)
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
                    self._accepting_mp4_data = False
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
            if media_type in {"audio/x-lpcm", "audio/x-private-ts-lpcm"}:
                self._attach_lpcm_audio_branch(pad)
                return
            if media_type == "audio/x-smpte-302m":
                self._attach_s302m_audio_branch(pad)
                return
            if media_type == "audio/mpeg":
                self._attach_aac_audio_branch(pad)
        except Exception as exc:  # pragma: no cover - runtime only
            with self._lock:
                if self._error_message is None:
                    self._error_message = str(exc)
                self._accepting_mp4_data = False
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

        gate_pad = queue.get_static_pad("sink")
        if gate_pad is None:
            raise RuntimeError(f"Could not access video recorder gate pad for {self._feed}.")
        gate_pad.add_probe(Gst.PadProbeType.BUFFER, self._video_gate_probe)

        src_pad = tail.get_static_pad("src")
        if src_pad is None:
            raise RuntimeError(f"Could not access video recorder src pad for {self._feed}.")

        mux_pad = _request_mux_pad(mux, "video")
        if src_pad.link(mux_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link video branch to MP4 mux for {self._feed}.")

        _sync_elements_with_parent(elements)

    def _attach_aac_audio_branch(self, pad: Gst.Pad) -> None:
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

    def _attach_lpcm_audio_branch(self, pad: Gst.Pad) -> None:
        with self._lock:
            if self._audio_branch_linked or self._pipeline is None or self._mux is None:
                return
            pipeline = self._pipeline
            mux = self._mux
            self._audio_branch_linked = True

        if Gst.ElementFactory.find("dvdlpcmdec") is None:
            raise RuntimeError(
                "dvdlpcmdec is required for MP4 recording from LPCM transport audio, but it is not available."
            )

        input_queue = _make_element("queue", f"{self._feed}_record_audio_input_queue")
        decoder = _make_element("dvdlpcmdec", f"{self._feed}_record_audio_dvdlpcmdec")
        convert = _make_element("audioconvert", f"{self._feed}_record_audio_convert")
        resample = _make_element("audioresample", f"{self._feed}_record_audio_resample")
        capsfilter = _make_element("capsfilter", f"{self._feed}_record_audio_caps")
        capsfilter.set_property(
            "caps",
            Gst.Caps.from_string(
                "audio/x-raw,"
                f"format=S16LE,layout=interleaved,channels={self._audio_channels},rate={self._audio_rate}"
            ),
        )
        encoder = _make_aac_encoder(self._feed, self._audio_bitrate)
        parser = _make_element("aacparse", f"{self._feed}_record_aacparse")
        output_queue = _make_element("queue", f"{self._feed}_record_audio_output_queue")
        elements = [input_queue, decoder, convert, resample, capsfilter, encoder, parser, output_queue]

        _add_and_link_elements(pipeline, elements)

        sink_pad = input_queue.get_static_pad("sink")
        if sink_pad is None or pad.link(sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link LPCM demux pad for {self._feed} recording.")

        gate_pad = capsfilter.get_static_pad("src")
        if gate_pad is None:
            raise RuntimeError(f"Could not access raw audio gate pad for {self._feed}.")
        gate_pad.add_probe(Gst.PadProbeType.BUFFER, self._audio_gate_probe)

        src_pad = output_queue.get_static_pad("src")
        if src_pad is None:
            raise RuntimeError(f"Could not access audio recorder src pad for {self._feed}.")

        mux_pad = _request_mux_pad(mux, "audio")
        if src_pad.link(mux_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link LPCM audio branch to MP4 mux for {self._feed}.")

        _sync_elements_with_parent(elements)

    def _attach_s302m_audio_branch(self, pad: Gst.Pad) -> None:
        with self._lock:
            if self._audio_branch_linked or self._pipeline is None or self._mux is None:
                return
            pipeline = self._pipeline
            mux = self._mux
            self._audio_branch_linked = True

        if Gst.ElementFactory.find("avdec_s302m") is None:
            raise RuntimeError(
                "avdec_s302m is required for MP4 recording from SMPTE 302M transport audio, but it is not available."
            )

        input_queue = _make_element("queue", f"{self._feed}_record_audio_input_queue")
        decoder = _make_element("avdec_s302m", f"{self._feed}_record_audio_avdec_s302m")
        convert = _make_element("audioconvert", f"{self._feed}_record_audio_convert")
        resample = _make_element("audioresample", f"{self._feed}_record_audio_resample")
        capsfilter = _make_element("capsfilter", f"{self._feed}_record_audio_caps")
        capsfilter.set_property(
            "caps",
            Gst.Caps.from_string(
                "audio/x-raw,"
                f"format=S16LE,layout=interleaved,channels={self._audio_channels},rate={self._audio_rate}"
            ),
        )
        encoder = _make_aac_encoder(self._feed, self._audio_bitrate)
        parser = _make_element("aacparse", f"{self._feed}_record_aacparse")
        output_queue = _make_element("queue", f"{self._feed}_record_audio_output_queue")
        elements = [input_queue, decoder, convert, resample, capsfilter, encoder, parser, output_queue]

        _add_and_link_elements(pipeline, elements)

        sink_pad = input_queue.get_static_pad("sink")
        if sink_pad is None or pad.link(sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link SMPTE 302M demux pad for {self._feed} recording.")

        gate_pad = capsfilter.get_static_pad("src")
        if gate_pad is None:
            raise RuntimeError(f"Could not access raw audio gate pad for {self._feed}.")
        gate_pad.add_probe(Gst.PadProbeType.BUFFER, self._audio_gate_probe)

        src_pad = output_queue.get_static_pad("src")
        if src_pad is None:
            raise RuntimeError(f"Could not access audio recorder src pad for {self._feed}.")

        mux_pad = _request_mux_pad(mux, "audio")
        if src_pad.link(mux_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Could not link SMPTE 302M audio branch to MP4 mux for {self._feed}.")

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

    def _has_raw_recording(self) -> bool:
        return self._paths.raw_temp_path.exists() and self._paths.raw_temp_path.stat().st_size > 0

    def _finalize_with_raw_fallback(self, reason: str) -> None:
        if not self._has_raw_recording():
            self._preserve_failed_recording()
            self._log(f"[{self._feed}] ERROR: No raw TS data was available for MP4 fallback. {reason}")
            return

        _safe_unlink(self._paths.raw_final_path)
        self._paths.raw_temp_path.replace(self._paths.raw_final_path)
        self._log(f"[{self._feed}] Falling back to raw TS remux after MP4 recorder failure. {reason}")

        if self._create_video_mp4_from_raw(copy_video=True) or self._create_video_mp4_from_raw(copy_video=False):
            _safe_unlink(self._paths.temp_path)
            self._extract_audio_fallback()
            self._log(f"[{self._feed}] Final video-only archive ready: {self._paths.final_path}")
            return

        self._preserve_failed_recording()
        self._log(
            f"[{self._feed}] ERROR: Could not create fallback video MP4; raw TS preserved: {self._paths.raw_final_path}"
        )

    def _create_video_mp4_from_raw(self, *, copy_video: bool) -> bool:
        _safe_unlink(self._paths.final_path)
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self._paths.raw_final_path),
            "-map",
            "0:v:0",
            "-an",
        ]
        if copy_video:
            command.extend(["-c:v", "copy"])
        else:
            command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"])
        command.extend(["-movflags", "+faststart", str(self._paths.final_path)])

        if self._run_ffmpeg(command, "video copy remux" if copy_video else "video transcode"):
            if self._paths.final_path.exists() and self._paths.final_path.stat().st_size > 0:
                return True
        _safe_unlink(self._paths.final_path)
        return False

    def _extract_audio_fallback(self) -> None:
        _safe_unlink(self._paths.audio_fallback_path)
        bitrate_kbps = max(1, self._audio_bitrate // 1000)
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self._paths.raw_final_path),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            f"{bitrate_kbps}k",
            str(self._paths.audio_fallback_path),
        ]
        if self._run_ffmpeg(command, "audio fallback extract"):
            if self._paths.audio_fallback_path.exists() and self._paths.audio_fallback_path.stat().st_size > 0:
                self._log(f"[{self._feed}] Separate fallback audio ready: {self._paths.audio_fallback_path}")
                return
        _safe_unlink(self._paths.audio_fallback_path)
        self._log(f"[{self._feed}] WARNING: Raw TS fallback did not produce separate audio.")

    def _run_ffmpeg(self, command: list[str], label: str) -> bool:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            self._log(f"[{self._feed}] ERROR: ffmpeg is required for {label} fallback but was not found.")
            return False
        except Exception as exc:  # pragma: no cover - subprocess/runtime only
            self._log(f"[{self._feed}] ERROR: ffmpeg {label} fallback could not run. {exc}")
            return False

        if result.returncode == 0:
            return True

        stderr = (result.stderr or "").strip()
        detail = f" {stderr}" if stderr else ""
        self._log(f"[{self._feed}] WARNING: ffmpeg {label} fallback failed with code {result.returncode}.{detail}")
        return False

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)


def _make_element(factory: str, name: str) -> Gst.Element:
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"Could not create GStreamer element: {factory}")
    return element


def _make_aac_encoder(feed: str, bitrate: int) -> Gst.Element:
    for factory in ("fdkaacenc", "voaacenc", "avenc_aac"):
        if Gst.ElementFactory.find(factory) is None:
            continue
        encoder = _make_element(factory, f"{feed}_{factory}_encoder")
        _set_optional_property(encoder, bitrate, "bitrate", "bit-rate", "bit_rate")
        return encoder
    raise RuntimeError("No AAC encoder is available for MP4 recording. Install fdkaacenc, voaacenc, or avenc_aac.")


def _add_and_link_elements(pipeline: Gst.Pipeline, elements: list[Gst.Element]) -> None:
    for element in elements:
        pipeline.add(element)
    for upstream, downstream in zip(elements, elements[1:]):
        if not upstream.link(downstream):
            raise RuntimeError(f"Could not link {upstream.get_name()} -> {downstream.get_name()}.")


def _sync_elements_with_parent(elements: list[Gst.Element]) -> None:
    for element in elements:
        element.sync_state_with_parent()


def _set_optional_property(element: Gst.Element, value: int, *property_names: str) -> None:
    for property_name in property_names:
        if element.find_property(property_name) is None:
            continue
        element.set_property(property_name, value)
        return


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


def _buffer_bytes(buffer: Gst.Buffer) -> bytes:
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        raise RuntimeError("Could not map GStreamer buffer.")

    try:
        return bytes(map_info.data)
    finally:
        buffer.unmap(map_info)


def _enum_label(value: object) -> str:
    value_nick = getattr(value, "value_nick", None)
    if value_nick:
        return str(value_nick)
    try:
        return str(int(value))  # type: ignore[arg-type]
    except Exception:
        return str(value)


def _is_idr_candidate(buffer: Gst.Buffer) -> bool:
    if _buffer_contains_h264_idr(buffer):
        return True

    flags = buffer.get_flags()
    if flags & Gst.BufferFlags.DELTA_UNIT:
        return False
    return True


def _buffer_contains_h264_idr(buffer: Gst.Buffer) -> bool:
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        return False

    try:
        data = map_info.data
        size = len(data)
        index = 0
        while index + 4 <= size:
            start_code_length = 0
            if data[index:index + 3] == b"\x00\x00\x01":
                start_code_length = 3
            elif index + 4 <= size and data[index:index + 4] == b"\x00\x00\x00\x01":
                start_code_length = 4

            if start_code_length == 0:
                index += 1
                continue

            nal_header_index = index + start_code_length
            if nal_header_index >= size:
                break

            nal_unit_type = data[nal_header_index] & 0x1F
            if nal_unit_type == 5:
                return True

            index = nal_header_index + 1

        return False
    finally:
        buffer.unmap(map_info)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
