#!/usr/bin/env python3
import argparse
import os
import signal
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


Gst.init(None)

# Ensure the parent directory is in sys.path to import shared helpers.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from audio_support import (
    alsa_runtime_device,
    build_input_pair_mix_element,
    build_output_pair_mix_element,
    build_webrtcdsp_properties,
    gst_escape,
    normalize_audio_channel_pair,
    normalize_audio_hardware_channels,
    validate_audio_rate,
    validate_local_audio_rate,
)
from config_loader import load_config
from live_queue_settings import build_queue_element


MAX_SYNC_DELAY_MS = 3000
DELAY_QUEUE_MAX_TIME_NS = 3_500_000_000
SYNC_DELAY_POLL_MS = 500


def parse_sync_delay_ms(value):
    try:
        delay_ms = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"sync delay must be an integer from 0 to {MAX_SYNC_DELAY_MS} ms"
        )
    if delay_ms < 0 or delay_ms > MAX_SYNC_DELAY_MS:
        raise argparse.ArgumentTypeError(
            f"sync delay must be between 0 and {MAX_SYNC_DELAY_MS} ms"
        )
    return delay_ms


def parse_channel_pair(value):
    try:
        pair = normalize_audio_channel_pair(value, "channel pair")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return f"{pair[0]}/{pair[1]}"


class SenderRuntime:
    def __init__(
        self,
        country,
        video_device=None,
        video_source="config",
        preview_pattern=None,
        audio_enabled=False,
        audio_device=None,
        playback_device=None,
        local_audio_rate=None,
        capture_input_channels="1/2",
        capture_hardware_channels=None,
        playback_output_channels="1/2",
        playback_hardware_channels=None,
        audio_source_mode="device",
        sender_audio_mode="aec",
        audio_delay_ms=0,
        sync_delay_file=None,
    ):
        self.country = country
        self.video_device = video_device
        self.video_source = video_source
        self.preview_pattern = preview_pattern
        self.audio_enabled = audio_enabled
        self.audio_device = audio_device
        self.playback_device = playback_device
        self.local_audio_rate = local_audio_rate
        self.capture_input_channels = capture_input_channels
        self.capture_hardware_channels = capture_hardware_channels
        self.playback_output_channels = playback_output_channels
        self.playback_hardware_channels = playback_hardware_channels
        self.audio_source_mode = audio_source_mode
        self.sender_audio_mode = sender_audio_mode
        self.audio_delay_ms = audio_delay_ms
        self.sync_delay_file = sync_delay_file

        self.pipeline = None
        self.loop = None
        self.clock = None
        self.server_ip = None
        self.video_send_port = None
        self.audio_send_port = None
        self.audio_recv_port = None
        self.exit_code = 0

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        cfg = load_config()
        self.server_ip = cfg.get("server_ip", "127.0.0.1")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        ports = cfg.get("ports", {})
        if self.country.lower() == "tn":
            self.video_send_port = ports.get("video_send_tn")
            self.audio_send_port = ports.get("audio_send_tn")
            self.audio_recv_port = ports.get("audio_receive_tn")
        else:
            self.video_send_port = ports.get("video_send_dk")
            self.audio_send_port = ports.get("audio_send_dk")
            self.audio_recv_port = ports.get("audio_receive_dk")

        if not self.video_send_port:
            print("ERROR: video send port not defined in config.")
            sys.exit(1)

        video_opts = cfg.get("video", {})
        streaming_settings_video = cfg.get("streaming_settings_video", "")
        video_encoder = video_opts.get("encoder", "x264enc")
        alignment = video_opts.get("alignment", "nal")
        config_interval = video_opts.get("config_interval", 1)
        video_width = video_opts.get("width", 1920)
        video_height = video_opts.get("height", 1080)
        video_framerate = video_opts.get("framerate", 30)
        video_source, source_label = self.resolve_video_source(video_opts)
        encoder_properties = self.build_encoder_properties(video_opts, video_encoder)
        profile_caps = self.build_profile_caps(video_opts, video_encoder)

        print(f"[Sender] Using video source: {source_label}", flush=True)

        sender_preview_queue = build_queue_element(
            cfg,
            ("sender", "preview"),
            {
                "leaky": "downstream",
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 0,
            },
        )
        sender_video_encode_queue = build_queue_element(
            cfg,
            ("sender", "video_encode"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 100,
            },
        )
        sender_mux_queue = build_queue_element(
            cfg,
            ("sender", "mux_input"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 100,
            },
        )
        preview_branch = ""
        if self.preview_pattern:
            preview_location = gst_escape(self.preview_pattern)
            preview_branch = f"""
                video_tee. ! {sender_preview_queue} !
                videoconvert ! videoscale ! videorate drop-only=true !
                video/x-raw,width=640,height=360,framerate=1/5 !
                jpegenc quality=70 !
                multifilesink location="{preview_location}" max-files=2 sync=false async=false
            """

        audio_branches = ""
        if self.audio_enabled:
            if not self.audio_send_port:
                print("ERROR: Missing audio send port in config.")
                sys.exit(1)
            if self.sender_audio_mode == "aec" and not self.audio_recv_port:
                print("ERROR: Missing audio receive port in config for sender playback/DSP mode.")
                sys.exit(1)
            audio_branches = self.build_audio_branches(cfg)

        pipeline_str = f"""
            {audio_branches}
            {video_source} !
            videoconvert ! videoscale ! videorate !
            video/x-raw,format=I420,width={video_width},height={video_height},framerate={video_framerate}/1,pixel-aspect-ratio=1/1,interlace-mode=progressive !
            tee name=video_tee

            video_tee. ! {sender_video_encode_queue} !
            {video_encoder} {encoder_properties} !
            video/x-h264,stream-format=byte-stream,alignment=au{profile_caps} !
            h264parse config-interval={config_interval} !
            {sender_mux_queue} !
            av_mux.

            {preview_branch}

            mpegtsmux name=av_mux alignment={alignment} !
            srtsink wait-for-connection=false
                uri="srt://{self.server_ip}:{self.video_send_port}?mode=caller&{streaming_settings_video}"
        """
        return pipeline_str.strip()

    def build_audio_branches(self, cfg):
        audio_opts = cfg.get("audio", {})
        dsp_cfg = cfg.get("webrtcdsp_settings", {})
        streaming_settings_audio = cfg.get("streaming_settings_audio", "")
        audio_srt_suffix = f"&{streaming_settings_audio}" if streaming_settings_audio else ""
        audio_format = audio_opts.get("format", "S16BE")
        transport_audio_rate = self.parse_audio_rate(audio_opts.get("rate", 32000))
        channels = int(audio_opts.get("channels", 2))
        if channels != 2:
            print("ERROR: audio.channels must be 2; sender hardware routing uses separate channel-pair settings.")
            sys.exit(1)
        encoding_name = audio_opts.get("encoding_name", "L16")
        playback_device = self.playback_device or audio_opts.get("playback_device", "default")
        runtime_playback_device = alsa_runtime_device(playback_device)
        playback_enabled = self.sender_audio_mode == "aec"
        try:
            local_audio_rate = validate_local_audio_rate(self.local_audio_rate, fallback=transport_audio_rate)
            capture_pair = normalize_audio_channel_pair(
                self.capture_input_channels,
                "sender capture input channels",
            )
            capture_hardware_channels = normalize_audio_hardware_channels(
                self.capture_hardware_channels,
                capture_pair,
                "sender capture hardware channels",
            )
            playback_pair = normalize_audio_channel_pair(
                self.playback_output_channels,
                "sender playback output channels",
            )
            playback_hardware_channels = normalize_audio_hardware_channels(
                self.playback_hardware_channels,
                playback_pair,
                "sender playback hardware channels",
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        normalized_transport_format = str(audio_format or "S16BE").strip().upper()
        if normalized_transport_format != "S16BE":
            print("ERROR: audio.format must be S16BE for the separate RTP L16 transport.")
            sys.exit(1)
        playback_input_queue = build_queue_element(
            cfg,
            ("sender", "playback_input"),
            {
                "max_size_buffers": 120,
                "max_size_bytes": 0,
                "max_size_time_ms": 150,
            },
        )
        playback_output_queue = build_queue_element(
            cfg,
            ("sender", "playback_output"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 75,
            },
        )
        audio_capture_queue = build_queue_element(
            cfg,
            ("sender", "audio_capture"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 75,
            },
        )
        audio_l16_output_queue = build_queue_element(
            cfg,
            ("sender", "audio_l16_output"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 75,
            },
        )
        audio_aac_output_queue = build_queue_element(
            cfg,
            ("sender", "audio_aac_output"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 100,
            },
        )
        audio_mux_queue = build_queue_element(
            cfg,
            ("sender", "mux_input"),
            {
                "max_size_buffers": 30,
                "max_size_bytes": 0,
                "max_size_time_ms": 100,
            },
        )

        if playback_enabled:
            try:
                transport_audio_rate = validate_audio_rate(transport_audio_rate)
                dsp_properties, resolved_dsp_cfg = build_webrtcdsp_properties(dsp_cfg)
            except ValueError as exc:
                print(f"ERROR: {exc}")
                sys.exit(1)
        else:
            dsp_properties = ""
            resolved_dsp_cfg = {}

        audio_source, source_label, uses_dsp = self.resolve_audio_source(audio_opts, local_audio_rate)
        aac_encoder = self.resolve_aac_encoder(audio_opts)
        enable_dsp = playback_enabled and uses_dsp
        capture_input_channel_count = capture_hardware_channels if uses_dsp else channels
        capture_mix_element = build_input_pair_mix_element(capture_pair, capture_hardware_channels) if uses_dsp else ""
        capture_pair_segment = f"! {capture_mix_element}" if capture_mix_element else ""
        playback_mix_element = build_output_pair_mix_element(playback_pair, playback_hardware_channels)
        playback_pair_segment = f"! {playback_mix_element}" if playback_mix_element else ""
        playback_output_channel_count = playback_hardware_channels if playback_mix_element else channels
        playback_branch = ""
        if playback_enabled:
            audio_delay_ns = self.audio_delay_ms * 1_000_000
            playback_branch = f"""
                srtsrc uri="srt://{self.server_ip}:{self.audio_recv_port}?mode=caller{audio_srt_suffix}" wait-for-connection=false !
                    {playback_input_queue}
                    ! application/x-rtp,media=audio,clock-rate={transport_audio_rate},encoding-name={encoding_name},channels={channels}
                    ! rtpL16depay
                    ! audioconvert
                    ! audioresample
                    ! audio/x-raw,format=S16LE,layout=interleaved,channels={channels},rate={transport_audio_rate}
                    ! queue name=audio_playback_delay_queue max-size-buffers=0 max-size-bytes=0 max-size-time={DELAY_QUEUE_MAX_TIME_NS} min-threshold-time={audio_delay_ns}
                    ! webrtcechoprobe name=playback_probe
                    ! {playback_output_queue}
                    ! audioconvert
                    ! audioresample
                    ! audio/x-raw,layout=interleaved,channels={channels},rate={local_audio_rate}
                    {playback_pair_segment}
                    ! audio/x-raw,layout=interleaved,channels={playback_output_channel_count},rate={local_audio_rate}
                    ! alsasink device="{gst_escape(runtime_playback_device)}" async=true
            """

        dsp_segment = f"! webrtcdsp probe=playback_probe {dsp_properties}" if enable_dsp else ""

        if playback_enabled:
            print(
                "[Sender] Sender playback + DSP mode active: remote audio is returned on the separate PCM path for local playback and acoustic echo cancellation.",
                flush=True,
            )
        else:
            print(
                "[Sender] Capture-only mode active: sender audio is transmitted, but remote playback and WebRTC DSP are disabled.",
                flush=True,
            )

        print(f"[Sender] Using audio source: {source_label}", flush=True)
        print(
            f"[Sender] Local audio hardware rate: {local_audio_rate} Hz "
            f"(transport/DSP rate: {transport_audio_rate} Hz).",
            flush=True,
        )
        if uses_dsp:
            print(
                f"[Sender] Capture input pair: {capture_pair[0]}/{capture_pair[1]} "
                f"(requesting {capture_hardware_channels} hardware channels).",
                flush=True,
            )
        print("[Sender] Live muxed audio transport: AAC in MPEG-TS.", flush=True)
        print("[Sender] Live separate audio transport: RTP L16 over SRT.", flush=True)
        if playback_enabled:
            print(f"[Sender] Using playback device: {playback_device}", flush=True)
            if runtime_playback_device != playback_device:
                print(f"[Sender] Runtime ALSA playback device: {runtime_playback_device}", flush=True)
            print(
                f"[Sender] Playback output pair: {playback_pair[0]}/{playback_pair[1]} "
                f"(requesting {playback_output_channel_count} hardware channels).",
                flush=True,
            )
            print(f"[Sender] Audio playback/probe delay: {self.audio_delay_ms} ms", flush=True)
        if enable_dsp:
            print(f"[Sender] Active WebRTC DSP settings: {resolved_dsp_cfg}", flush=True)
        elif playback_enabled:
            print("[Sender] WebRTC DSP is bypassed because the sender audio source is a test signal.", flush=True)

        return f"""
            {playback_branch}

            {audio_source}
                ! {audio_capture_queue}
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,layout=interleaved,channels={capture_input_channel_count},rate={local_audio_rate}
                {capture_pair_segment}
                ! audio/x-raw,format=S16LE,layout=interleaved,channels={channels},rate={local_audio_rate}
                ! audioresample
                ! audio/x-raw,format=S16LE,layout=interleaved,channels={channels},rate={transport_audio_rate}
                {dsp_segment}
                ! tee name=audio_capture_tee

            audio_capture_tee. ! {audio_l16_output_queue}
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16BE,layout=interleaved,channels={channels},rate={transport_audio_rate}
                ! rtpL16pay
                ! srtsink wait-for-connection=false
                    uri="srt://{self.server_ip}:{self.audio_send_port}?mode=caller&{streaming_settings_audio}"

            audio_capture_tee. ! {audio_aac_output_queue}
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,layout=interleaved,channels={channels},rate={transport_audio_rate}
                ! {aac_encoder}
                ! aacparse
                ! {audio_mux_queue}
                ! av_mux.
        """

    def parse_audio_rate(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            print(f"ERROR: audio.rate must be an integer; got {value!r}.")
            sys.exit(1)

    def resolve_video_source(self, video_opts):
        if self.video_device:
            return f'v4l2src device="{gst_escape(self.video_device)}" do-timestamp=true', f"camera {self.video_device}"

        if (self.video_source or "config").strip().lower() == "test":
            pattern = video_opts.get("test_source_pattern", "ball")
            return f"videotestsrc pattern={pattern} is-live=true do-timestamp=true", f"test source ({pattern})"

        config_source = video_opts.get("source", "v4l2src device=/dev/video0")
        return config_source, f"config source ({config_source})"

    def resolve_audio_source(self, audio_opts, audio_rate):
        if (self.audio_source_mode or "device").strip().lower() == "test":
            wave = audio_opts.get("test_source_wave", "sine")
            freq = self.first_numeric(audio_opts.get("test_source_freq"), 440.0)
            volume = self.first_numeric(audio_opts.get("test_source_volume"), 0.2)
            return (
                f"audiotestsrc wave={wave} freq={freq} volume={volume} is-live=true do-timestamp=true",
                f"test audio ({wave})",
                False,
            )

        device = self.audio_device or audio_opts.get("device", "default")
        runtime_device = alsa_runtime_device(device)
        label = f"capture device {device} at {audio_rate} Hz"
        if runtime_device != device:
            label += f" (runtime ALSA device {runtime_device})"
        return (
            f'alsasrc device="{gst_escape(runtime_device)}" do-timestamp=true',
            label,
            True,
        )

    def resolve_aac_encoder(self, audio_opts):
        aac_encoder = audio_opts.get("aac_encoder")
        if aac_encoder:
            return aac_encoder

        for factory in ("fdkaacenc", "voaacenc", "avenc_aac"):
            if Gst.ElementFactory.find(factory) is not None:
                bitrate = int(audio_opts.get("aac_bitrate", 128000))
                if factory == "fdkaacenc":
                    return f"{factory} bitrate={bitrate}"
                if factory == "voaacenc":
                    return f"{factory} bitrate={bitrate}"
                if factory == "avenc_aac":
                    return f"{factory} bitrate={bitrate}"

        print("ERROR: No AAC encoder is available. Install fdkaacenc, voaacenc, or avenc_aac.")
        sys.exit(1)

    def build_encoder_properties(self, video_opts, video_encoder):
        bitrate = video_opts.get("bitrate", 1000)
        key_int_max = video_opts.get("key_int_max", 15)
        tune = video_opts.get("tune", "zerolatency")
        bframes = video_opts.get("bframes", 0)
        aud_bool = video_opts.get("aud", True)
        byte_stream = video_opts.get("byte_stream", True)

        properties = [
            f"bitrate={bitrate}",
            f"key-int-max={key_int_max}",
            f"bframes={bframes}",
            f'aud={"true" if aud_bool else "false"}',
            f'byte-stream={"true" if byte_stream else "false"}',
        ]
        if tune:
            properties.append(f"tune={tune}")

        if (video_encoder or "").strip() == "x264enc":
            speed_preset = self.first_non_empty(video_opts, "speed_preset", "speed-preset")
            pass_mode = self.first_non_empty(video_opts, "pass")
            quantizer = video_opts.get("quantizer")
            option_string = self.first_non_empty(video_opts, "option_string", "option_str", "option-string")

            if speed_preset:
                properties.append(f"speed-preset={speed_preset}")
            if pass_mode:
                properties.append(f"pass={pass_mode}")
            if quantizer not in {None, ""}:
                properties.append(f"quantizer={quantizer}")
            if option_string:
                properties.append(f'option-string="{gst_escape(str(option_string))}"')

        return " ".join(properties)

    def build_profile_caps(self, video_opts, video_encoder):
        if (video_encoder or "").strip() != "x264enc":
            return ""
        profile = self.first_non_empty(video_opts, "profile")
        if not profile:
            return ""
        return f",profile={profile}"

    def first_non_empty(self, mapping, *keys):
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
            else:
                return value
        return None

    def first_numeric(self, value, default):
        if value in {None, ""}:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def on_message(self, bus, message):
        source_name = message.src.get_name() if message.src is not None else "unknown"
        if message.type == Gst.MessageType.EOS:
            print(f"[Sender] End of Stream from {source_name}", flush=True)
            self.exit_code = 1
            self.stop()
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[Sender] ERROR from {source_name} -> {err}", flush=True)
            if debug:
                print(f"[Sender] Debug info: {debug}", flush=True)
            self.exit_code = 1
            self.stop()

    def poll_sync_delay_file(self):
        if self.pipeline is None or not self.sync_delay_file:
            return True

        try:
            with open(self.sync_delay_file, encoding="utf-8") as delay_file:
                raw_value = delay_file.read().strip()
        except OSError:
            return True

        try:
            next_delay_ms = parse_sync_delay_ms(raw_value or 0)
        except argparse.ArgumentTypeError as exc:
            print(f"[Sender] Ignoring invalid sync delay file value: {exc}", flush=True)
            return True

        if next_delay_ms != self.audio_delay_ms:
            self.apply_audio_delay(next_delay_ms)
        return True

    def apply_audio_delay(self, delay_ms):
        if self.pipeline is None:
            self.audio_delay_ms = delay_ms
            return

        delay_queue = self.pipeline.get_by_name("audio_playback_delay_queue")
        if delay_queue is None:
            self.audio_delay_ms = delay_ms
            return

        delay_queue.set_property("min-threshold-time", delay_ms * 1_000_000)
        self.audio_delay_ms = delay_ms
        print(f"[Sender] Audio playback/probe delay updated to {delay_ms} ms.", flush=True)

    def run(self):
        self.exit_code = 0
        pipeline_str = self.build_pipeline()
        print("[Sender] Pipeline:\n" + pipeline_str + "\n", flush=True)
        if self.preview_pattern:
            os.makedirs(os.path.dirname(os.path.abspath(self.preview_pattern)), exist_ok=True)
        self.pipeline = Gst.parse_launch(pipeline_str)

        if self.clock:
            self.pipeline.use_clock(self.clock)
            self.pipeline.set_locked_state(True)
        else:
            self.pipeline.use_clock(Gst.SystemClock.obtain())
            self.pipeline.set_locked_state(True)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        if self.sender_audio_mode == "aec" and self.audio_enabled and self.sync_delay_file:
            GLib.timeout_add(SYNC_DELAY_POLL_MS, self.poll_sync_delay_file)

        print("[Sender] Setting state to PLAYING...")
        self._set_pipeline_state(Gst.State.PLAYING, timeout_seconds=5.0, allow_pending=True)

        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as exc:
            print(f"[Sender] Exception -> {exc}")
        finally:
            self._set_pipeline_state(Gst.State.NULL, timeout_seconds=10.0, suppress_errors=True)
            print("[Sender] Pipeline stopped.")
        return self.exit_code

    def stop(self):
        if self.loop:
            self.loop.quit()

    def _set_pipeline_state(
        self,
        target_state,
        timeout_seconds=5.0,
        suppress_errors=False,
        allow_pending=False,
    ):
        if self.pipeline is None:
            return

        state_change = self.pipeline.set_state(target_state)
        if state_change == Gst.StateChangeReturn.FAILURE:
            message = f"[Sender] Could not change pipeline state to {self._state_label(target_state)}."
            if suppress_errors:
                print(message, flush=True)
                return
            raise RuntimeError(message)

        timeout_ns = int(timeout_seconds * Gst.SECOND)
        result, current_state, pending_state = self.pipeline.get_state(timeout_ns)
        if result == Gst.StateChangeReturn.FAILURE:
            message = f"[Sender] Pipeline failed while changing state to {self._state_label(target_state)}."
            if suppress_errors:
                print(message, flush=True)
                return
            raise RuntimeError(message)
        if allow_pending and target_state == Gst.State.PLAYING:
            if result in {Gst.StateChangeReturn.ASYNC, Gst.StateChangeReturn.NO_PREROLL}:
                print("[Sender] Pipeline armed and waiting for stream connections/data.", flush=True)
                return
            if pending_state == target_state:
                print("[Sender] Pipeline armed and waiting to complete PLAYING.", flush=True)
                return
        if result == Gst.StateChangeReturn.ASYNC:
            message = (
                f"[Sender] Timed out while waiting for pipeline state {self._state_label(target_state)}; "
                f"current={self._state_label(current_state)}, pending={self._state_label(pending_state)}."
            )
            if suppress_errors:
                print(message, flush=True)
                return
            raise RuntimeError(message)
        if current_state != target_state:
            message = (
                f"[Sender] Pipeline reached unexpected state {self._state_label(current_state)} "
                f"while targeting {self._state_label(target_state)}."
            )
            if suppress_errors:
                print(message, flush=True)
                return
            raise RuntimeError(message)

    def _state_label(self, state):
        try:
            return Gst.Element.state_get_name(state)
        except Exception:
            return str(state)


def main():
    parser = argparse.ArgumentParser(
        description="Sender runtime with live H.264 + AAC MPEG-TS transport plus separate RTP L16 audio relay."
    )
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument("--with-audio", dest="with_audio", action="store_true", help="Enable sender audio capture/playback branches.")
    audio_group.add_argument("--no-audio", dest="with_audio", action="store_false", help="Run video only.")
    parser.set_defaults(with_audio=None)
    parser.add_argument("--device", help="ALSA audio capture device name (for example hw:1,0).")
    parser.add_argument("--playback-device", help="ALSA audio playback device name (for example hw:0,0).")
    parser.add_argument("--audio-rate", type=int, help="Local sender ALSA hardware sample rate. Audio is resampled to the configured transport/DSP rate after capture and before playback.")
    parser.add_argument("--capture-input-channels", type=parse_channel_pair, default="1/2", help="1-based sender hardware capture stereo pair, for example 1/2 or 3/4.")
    parser.add_argument("--capture-hardware-channels", type=int, help="Sender capture channel count to request from ALSA before pair mapping.")
    parser.add_argument("--playback-output-channels", type=parse_channel_pair, default="1/2", help="1-based sender hardware playback stereo pair, for example 1/2 or 5/6.")
    parser.add_argument("--playback-hardware-channels", type=int, help="Sender playback channel count to request from ALSA before output pair mapping.")
    parser.add_argument("--audio-source", choices=["device", "test"], default="device", help="Audio source mode. Use 'test' for audiotestsrc instead of a capture device.")
    parser.add_argument("--sender-audio-mode", choices=["aec", "capture-only"], default="aec", help="Sender audio mode. Use 'capture-only' to disable remote playback and WebRTC DSP on the sender.")
    parser.add_argument("--audio-delay-ms", type=parse_sync_delay_ms, default=0, help="Initial sender remote-audio playback/probe delay in milliseconds for A/V sync calibration.")
    parser.add_argument("--sync-delay-file", help="Optional control file containing the live sender audio delay in milliseconds.")
    parser.add_argument("--video-device", help="Video device path override, for example /host-dev/video2.")
    parser.add_argument("--video-source", choices=["config", "test"], default="config", help="Video source mode. Use 'test' to send a test signal instead of a camera.")
    parser.add_argument("--preview-pattern", help="Optional JPEG snapshot output pattern, for example /mnt/tbdrive/previews/sender-tn-preview-%05d.jpg.")
    parser.add_argument("--supervised", action="store_true", help="Run once and exit on failure so the control app can manage fallback/retry.")
    args = parser.parse_args()

    if args.with_audio is None:
        run_audio_input = input("Do you want to run sender audio? (y/n): ").strip().lower()
        run_audio = run_audio_input.startswith("y")
    else:
        run_audio = args.with_audio

    audio_source_mode = args.audio_source
    sender_audio_mode = args.sender_audio_mode
    audio_device = args.device
    if run_audio and args.with_audio is None:
        source_input = input("Enter the audio device name, 'test' for an audio test signal, or leave blank for default: ").strip()
        if source_input.lower() == "test":
            audio_source_mode = "test"
            audio_device = None
        elif source_input:
            audio_device = source_input
        playback_input = input("Enable sender playback and DSP? (y/n, default y): ").strip().lower()
        if playback_input.startswith("n"):
            sender_audio_mode = "capture-only"

    sender = SenderRuntime(
        args.country,
        video_device=args.video_device,
        video_source=args.video_source,
        preview_pattern=args.preview_pattern,
        audio_enabled=run_audio,
        audio_device=audio_device,
        playback_device=args.playback_device,
        local_audio_rate=args.audio_rate,
        capture_input_channels=args.capture_input_channels,
        capture_hardware_channels=args.capture_hardware_channels,
        playback_output_channels=args.playback_output_channels,
        playback_hardware_channels=args.playback_hardware_channels,
        audio_source_mode=audio_source_mode,
        sender_audio_mode=sender_audio_mode,
        audio_delay_ms=args.audio_delay_ms,
        sync_delay_file=args.sync_delay_file,
    )
    shared_clock = Gst.SystemClock.obtain()
    sender.set_clock(shared_clock)

    def handle_signal(sig, frame):
        print("[Main] Interrupt received, shutting down...")
        sender.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.supervised:
        try:
            exit_code = sender.run()
        except Exception as exc:
            print(f"[Main] Sender exception: {exc}", flush=True)
            exit_code = 1
        sys.exit(exit_code)

    while True:
        try:
            sender.run()
        except Exception as exc:
            print(f"[Main] Sender exception: {exc}")
        print("[Main] Sender stopped unexpectedly. Restarting in 5 seconds...")
        time.sleep(5)


if __name__ == "__main__":
    main()
