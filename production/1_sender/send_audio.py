#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import os
import sys
import signal
import argparse
import time

# Ensure the parent directory is in sys.path to import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

# Initialize GStreamer.
Gst.init(None)


SUPPORTED_WEBRTC_SAMPLE_RATES = {8000, 16000, 32000, 48000}
WEBRTC_DSP_PROPERTY_ORDER = [
    "compression-gain-db",
    "delay-agnostic",
    "echo-cancel",
    "echo-suppression-level",
    "experimental-agc",
    "extended-filter",
    "gain-control",
    "gain-control-mode",
    "high-pass-filter",
    "limiter",
    "noise-suppression",
    "noise-suppression-level",
    "startup-min-volume",
    "target-level-dbfs",
    "voice-detection",
    "voice-detection-frame-size-ms",
    "voice-detection-likelihood",
]
WEBRTC_DSP_DEFAULTS = {
    "compression-gain-db": 9,
    "delay-agnostic": False,
    "echo-cancel": True,
    "echo-suppression-level": "moderate",
    "experimental-agc": False,
    "extended-filter": False,
    "gain-control": True,
    "gain-control-mode": "adaptive-digital",
    "high-pass-filter": True,
    "limiter": True,
    "noise-suppression": True,
    "noise-suppression-level": "moderate",
    "startup-min-volume": 12,
    "target-level-dbfs": 3,
    "voice-detection": False,
    "voice-detection-frame-size-ms": 0,
    "voice-detection-likelihood": "low",
}
WEBRTC_DSP_ENUM_VALUES = {
    "echo-suppression-level": {"low", "moderate", "high"},
    "gain-control-mode": {"adaptive-digital", "fixed-digital", "adaptive-analog"},
    "noise-suppression-level": {"low", "moderate", "high", "very-high"},
    "voice-detection-likelihood": {"very-low", "low", "moderate", "high"},
}
WEBRTC_DSP_BOOL_KEYS = {
    "delay-agnostic",
    "echo-cancel",
    "experimental-agc",
    "extended-filter",
    "gain-control",
    "high-pass-filter",
    "limiter",
    "noise-suppression",
    "voice-detection",
}
WEBRTC_DSP_INT_KEYS = {
    "compression-gain-db",
    "startup-min-volume",
    "target-level-dbfs",
    "voice-detection-frame-size-ms",
}

#########################################
# AudioSender Class
#########################################
class AudioSender:
    def __init__(self, country, device=None):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.clock = None

        # Load configuration.
        config = load_config()

        # Allow the dashboard to override the capture device while playback stays on the configured/default sink.
        self.capture_device = device or config.get("audio", {}).get("device", "default")
        self.playback_device = config.get("audio", {}).get("playback_device", "default")

        self.server_ip = None
        self.audio_send_port = None
        self.audio_recv_port = None

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        config = load_config()

        # Server IP and ports
        self.server_ip = config.get("server_ip", "127.0.0.1")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        if self.country.lower() == "tn":
            self.audio_send_port = config.get("ports", {}).get("audio_send_tn")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_tn")
        else:
            self.audio_send_port = config.get("ports", {}).get("audio_send_dk")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_dk")

        if not self.audio_send_port or not self.audio_recv_port:
            print("ERROR: Missing audio ports in config (send/receive).")
            sys.exit(1)

        # Audio settings
        audio_format = config.get("audio", {}).get("format", "S16LE")
        audio_rate = config.get("audio", {}).get("rate", 48000)
        channels = config.get("audio", {}).get("channels", 2)
        encoding_name = config.get("audio", {}).get("encoding_name", "L16")
        streaming_settings = config.get("streaming_settings_audio", "")
        dsp_cfg = config.get("webrtcdsp_settings", {})

        try:
            audio_rate = self.validate_audio_rate(audio_rate)
            dsp_properties, resolved_dsp_cfg = self.build_dsp_properties(dsp_cfg)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

        print(
            "[AudioSender] Sender-side audio topology active: local microphone capture and local remote-audio playback share the same pipeline for AEC.",
            flush=True,
        )
        print(f"[AudioSender] Active WebRTC DSP settings: {resolved_dsp_cfg}", flush=True)

        pipeline_str = f"""
            srtsrc uri="srt://{self.server_ip}:{self.audio_recv_port}?mode=caller" wait-for-connection=false 
                ! queue max-size-time=2000000000 max-size-buffers=500
                ! application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={channels}
                ! rtpL16depay
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcechoprobe name=playback_probe
                ! queue
                ! alsasink device="{self.gst_escape(self.playback_device)}" async=true

            alsasrc device="{self.gst_escape(self.capture_device)}"
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcdsp probe=playback_probe {dsp_properties}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format={audio_format},channels={channels},rate={audio_rate}
                ! rtpL16pay
                ! srtsink uri="srt://{self.server_ip}:{self.audio_send_port}?mode=caller&{streaming_settings}"
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            print("[AudioSender] End of Stream")
            self.stop()
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[AudioSender] ERROR -> {err}")
            if debug:
                print(f"[AudioSender] Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("[AudioSender] Pipeline:\n" + pipeline_str + "\n", flush=True)
        self.pipeline = Gst.parse_launch(pipeline_str)

        # Set clock
        if self.clock:
            self.pipeline.use_clock(self.clock)
            self.pipeline.set_locked_state(True)
        else:
            self.pipeline.use_clock(Gst.SystemClock.obtain())
            self.pipeline.set_locked_state(True)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        print("[AudioSender] Setting state to PLAYING...")
        self.pipeline.set_state(Gst.State.PLAYING)

        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"[AudioSender] Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("[AudioSender] Pipeline stopped.")

    def stop(self):
        if self.loop:
            self.loop.quit()

    def validate_audio_rate(self, audio_rate):
        try:
            rate = int(audio_rate)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"audio.rate must be an integer supported by webrtcdsp; got {audio_rate!r}."
            ) from exc

        if rate not in SUPPORTED_WEBRTC_SAMPLE_RATES:
            supported = ", ".join(str(value) for value in sorted(SUPPORTED_WEBRTC_SAMPLE_RATES))
            raise ValueError(
                f"audio.rate={rate} is not supported by webrtcdsp. Use one of: {supported}."
            )

        return rate

    def build_dsp_properties(self, dsp_cfg):
        if dsp_cfg is None:
            dsp_cfg = {}
        if not isinstance(dsp_cfg, dict):
            raise ValueError("webrtcdsp_settings must be a YAML mapping.")

        unknown_keys = sorted(set(dsp_cfg) - set(WEBRTC_DSP_PROPERTY_ORDER))
        if unknown_keys:
            raise ValueError(
                "Unsupported webrtcdsp_settings keys: "
                + ", ".join(unknown_keys)
                + ". Remove them or map them to real webrtcdsp properties."
            )

        resolved = {}
        properties = []
        for key in WEBRTC_DSP_PROPERTY_ORDER:
            raw_value = dsp_cfg.get(key, WEBRTC_DSP_DEFAULTS[key])
            resolved_value = self.normalize_dsp_value(key, raw_value)
            resolved[key] = resolved_value
            properties.append(f"{key}={self.format_gst_value(resolved_value)}")

        return " ".join(properties), resolved

    def normalize_dsp_value(self, key, value):
        if key in WEBRTC_DSP_BOOL_KEYS:
            return self.normalize_bool(key, value)
        if key in WEBRTC_DSP_INT_KEYS:
            return self.normalize_int(key, value)
        if key in WEBRTC_DSP_ENUM_VALUES:
            return self.normalize_enum(key, value, WEBRTC_DSP_ENUM_VALUES[key])
        raise ValueError(f"Unsupported webrtcdsp property mapping for {key}.")

    def normalize_bool(self, key, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "on", "1"}:
                return True
            if normalized in {"false", "no", "off", "0"}:
                return False
        raise ValueError(f"webrtcdsp_settings.{key} must be a boolean; got {value!r}.")

    def normalize_int(self, key, value):
        if isinstance(value, bool):
            raise ValueError(f"webrtcdsp_settings.{key} must be an integer; got {value!r}.")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"webrtcdsp_settings.{key} must be an integer; got {value!r}.") from exc

    def normalize_enum(self, key, value, allowed_values):
        if not isinstance(value, str):
            raise ValueError(
                f"webrtcdsp_settings.{key} must be one of {sorted(allowed_values)}; got {value!r}."
            )
        normalized = value.strip().lower()
        if normalized not in allowed_values:
            raise ValueError(
                f"webrtcdsp_settings.{key} must be one of {sorted(allowed_values)}; got {value!r}."
            )
        return normalized

    def format_gst_value(self, value):
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, int):
            return str(value)
        return value

    def gst_escape(self, value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

#########################################
# Signal Handler and Main
#########################################
def signal_handler(sig, frame, sender):
    print("[AudioSender] Interrupt received, shutting down...")
    sender.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Audio Sender Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    parser.add_argument("--device", help="ALSA audio capture device name (e.g., 'hw:1,0')")
    args = parser.parse_args()

    audio_sender = AudioSender(args.country, args.device)
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, audio_sender))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, audio_sender))

    shared_clock = Gst.SystemClock.obtain()
    audio_sender.set_clock(shared_clock)

    while True:
        try:
            audio_sender.run()
        except Exception as e:
            print(f"[Main] Audio sender exception: {e}")
        print("[Main] Audio sender stopped unexpectedly. Restarting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    main()
