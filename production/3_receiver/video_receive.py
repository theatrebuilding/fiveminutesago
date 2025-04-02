#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import os
import sys
import signal
import argparse

from config_loader import load_config

class VideoReceiver:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_address = None
        self.receive_port = None
        self.clock = None

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        # Choose the video receive port based on the country.
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")
        
        pipeline_str = f"""
            srtsrc uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100" 
                ! queue max-size-time=2000000000 max-size-buffers=500 
                ! tsdemux name=demux 
                demux. ! queue ! h264parse config-interval=1 
                ! avdec_h264 
                ! videoconvert 
                ! videoscale 
                ! video/x-raw,width=1920,height=1080 
                ! kmssink sync=false
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("VideoReceiver: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"VideoReceiver: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("VideoReceiver: Pipeline:\n", pipeline_str, "\n")

        self.pipeline = Gst.parse_launch(pipeline_str)
        # Use the shared clock if available; otherwise, obtain the system clock.
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
            print(f"VideoReceiver: Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("VideoReceiver: Pipeline stopped.")

    def stop(self):
        if self.loop and self.loop.is_running():
            print("VideoReceiver: Quitting main loop...")
            self.loop.quit()

def signal_handler(sig, frame, receiver):
    print("VideoReceiver: Interrupt received, stopping pipeline...")
    receiver.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Video Receiver Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    receiver = VideoReceiver(args.country)

    # Setup signal handling to allow graceful shutdown.
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))

    receiver.run()

if __name__ == "__main__":
    Gst.init(None)
    main()
