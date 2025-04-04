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

    def build_pipeline(self):
        # Load configuration and determine the appropriate SRT port.
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")
        
        # Build a pipeline using fallbacksrc.
        # - "uri" is the primary stream (your SRT stream).
        # - "fallback-uri" is set to a videotestsrc URI (here using the "ball" pattern).
        # - "fallback-video-caps" ensures the fallback stream has the same caps.
        # - "timeout" is in nanoseconds (5e9 = 5 seconds).
        # - "auto-switch" is true so that the element automatically switches between primary and fallback.
        pipeline_str = f"""
            fallbacksrc name=fsrc 
                uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100" 
                fallback-uri="videotestsrc://?pattern=ball" 
                fallback-video-caps="video/x-raw,width=1920,height=1080" 
                timeout=5000000000 auto-switch=true
            ! kmssink sync=false
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            print("VideoReceiver: End of Stream")
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print("VideoReceiver: ERROR ->", err)
            if debug:
                print("Debug info:", debug)

    def run(self):
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
            print("VideoReceiver: Exception ->", e)
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
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))
    receiver.run()

if __name__ == "__main__":
    Gst.init(None)
    main()
