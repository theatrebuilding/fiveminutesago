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
        self.server_ip = None
        self.audio_send_port = None

    def build_pipeline(self):
        config = load_config()
        self.server_ip = config.get("server_ip")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)
        
        # Choose the audio send port based on the country.
        if self.country.lower() == "tn":
            self.audio_send_port = config.get("ports", {}).get("audio_send_tn")
        else:
            self.audio_send_port = config.get("ports", {}).get("audio_send_dk")
        
        streaming_settings = config.get("streaming_settings_audio", "")
        source = config.get("audio", {}).get("source", "autoaudiosrc")
        audio_format = config.get("audio", {}).get("format", "S16BE")
        audio_rate = config.get("audio", {}).get("rate", 32000)
        
        # Build the pipeline string.
        pipeline_str = f"""
            {source} device={self.device} ! 
            webrtcdsp echo-cancel=false !
            audioconvert ! audioresample !
            audio/x-raw,format={audio_format},channels=1,rate={audio_rate} !
            audioconvert ! audio/x-raw,channels=2 !
            rtpL16pay !
            srtsink uri="srt://{self.server_ip}:{self.audio_send_port}?mode=caller&{streaming_settings}"
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
        print("AudioSender: Pipeline:\n", pipeline_str, "\n")
        self.pipeline = Gst.parse_launch(pipeline_str)
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
    parser = argparse.ArgumentParser(description="Audio Sender Script")
    parser.add_argument("--device", required=True, help="Audio device (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()
    sender = AudioSender(args.device, args.country)
    sender.run()
