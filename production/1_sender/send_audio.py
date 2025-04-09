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

        # Allow override via CLI.
        self.device = device or config.get("audio", {}).get("device", "default")

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
        echo_cancel = dsp_cfg.get("echo-cancel", True)

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
                ! alsasink device={self.device} async=true

            alsasrc device={self.device}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcdsp echo-cancel={str(echo_cancel).lower()}
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
    parser.add_argument("--device", help="ALSA audio device name (e.g., 'hw:1,0' or 'default')")
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
