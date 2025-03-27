#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import os
import sys
import signal
import argparse

# Import the configuration loader
# Insert parent directory for config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

class VideoReceiver:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_address = None
        self.receive_port = None

    def build_pipeline(self):
        """
        Build the GStreamer pipeline string for receiving video.
        The pipeline uses an input-selector that takes the live stream from the SRT source
        and a fallback branch that uses videotestsrc (colorbars).
        """
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        # Choose the video receive port based on the country.
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")

        # Build the pipeline string:
        pipeline_str = f"""
            input-selector name=selector ! queue ! videoconvert ! videoscale ! video/x-raw,width=1920,height=1080 ! kmssink sync=false 
            srtsrc uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100" 
                ! queue max-size-time=2000000000 max-size-buffers=500 ! tsdemux name=demux 
                demux. ! queue ! h264parse config-interval=1 ! avdec_h264 ! selector. 
            videotestsrc pattern=snow ! video/x-raw,format=I420,width=1920,height=1080 ! selector.
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        """
        Handle messages from the GStreamer bus.
        """
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
        """
        Parse the pipeline string, set up the bus watch, and run the main loop.
        """
        pipeline_str = self.build_pipeline()
        print("VideoReceiver: Pipeline:\n", pipeline_str, "\n")

        self.pipeline = Gst.parse_launch(pipeline_str)
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
        """
        Stop the GStreamer pipeline and exit the main loop.
        """
        if self.loop:
            self.loop.quit()

def signal_handler(sig, frame, receiver):
    print("VideoReceiver: Interrupt received, stopping pipeline...")
    receiver.stop()
    sys.exit(0)

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Video Receiver Script with Fallback (Colorbars)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    receiver = VideoReceiver(args.country)

    # Handle termination signals
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))

    receiver.run()

if __name__ == "__main__":
    Gst.init(None)
    main()
