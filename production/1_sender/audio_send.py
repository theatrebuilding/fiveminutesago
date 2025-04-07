#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import os
import sys
import signal

# Insert parent directory to access config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

class AudioSender:

    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.pipeline = None
        self.loop = None
        self.clock = None

        # Will fill these from config:
        self.server_ip = None
        self.audio_send_port = None
        self.audio_recv_port = None

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        config = load_config()

        # Server or remote IP for SRT:
        self.server_ip = config.get("server_ip", "127.0.0.1")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        # Decide which send/receive ports to use based on country
        if self.country.lower() == "tn":
            self.audio_send_port = config.get("ports", {}).get("audio_send_tn")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_tn")
        else:
            self.audio_send_port = config.get("ports", {}).get("audio_send_dk")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_dk")

        if not self.audio_send_port or not self.audio_recv_port:
            print("ERROR: Missing audio ports in config (send/receive).")
            sys.exit(1)

        # Basic audio parameters
        audio_format = config.get("audio", {}).get("format", "S16LE")  # Must be L16 or S16LE for webrtcdsp
        audio_rate = config.get("audio", {}).get("rate", 48000)
        channels = config.get("audio", {}).get("channels", 2)
        encoding_name = config.get("audio", {}).get("encoding_name", "L16")

        # SRT streaming settings (for sending)
        streaming_settings = config.get("streaming_settings_audio", "")

        # webrtcdsp settings
        dsp_cfg = config.get("webrtcdsp_settings", {})
        echo_cancel = dsp_cfg.get("echo-cancel", True)
        noise_suppression = dsp_cfg.get("noise-suppression", True)
        extended_filter = dsp_cfg.get("extended-filter", True)
        compression_gain = dsp_cfg.get("compression-gain-db", 0)
        echo_supp_level = dsp_cfg.get("echo-suppression-level", "moderate")
        gain_control = dsp_cfg.get("gain-control", False)
        high_pass = dsp_cfg.get("high-pass-filter", False)
        limiter = dsp_cfg.get("limiter", True)

        pipeline_str = f"""
            srtsrc uri="srt://{self.server_ip}:{self.audio_recv_port}?mode=caller" wait-for-connection=false
                ! queue max-size-time=2000000000 max-size-buffers=500
                ! application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={channels}
                ! rtpL16depay
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcechoprobe
                ! queue
                ! alsasink device={self.device} async=false sync=false

            alsasrc device={self.device}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcdsp
                    echo-cancel={str(echo_cancel).lower()}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format={audio_format},channels={channels},rate={audio_rate}
                ! rtpL16pay
                ! srtsink uri="srt://{self.server_ip}:{self.audio_send_port}?mode=caller&{streaming_settings}" sync=false

        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("AudioSender: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"AudioSender: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("AudioSender (Send+Receive) Pipeline:\n" + pipeline_str + "\n", flush=True)

        self.pipeline = Gst.parse_launch(pipeline_str)

        # Use the shared clock if provided.
        if self.clock:
            self.pipeline.use_clock(self.clock)
        else:
            system_clock = Gst.SystemClock.obtain()
            self.pipeline.use_clock(system_clock)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"AudioSender: Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("AudioSender: Pipeline stopped.")

    def stop(self):
        if self.loop:
            self.loop.quit()

if __name__ == "__main__":
    # For standalone testing.
    import argparse
    parser = argparse.ArgumentParser(description="Audio Sender/Receiver with Echo Cancellation")
    parser.add_argument("--device", required=True, help="ALSA device (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()
    sender = AudioSender(args.device, args.country)
    sender.run()
