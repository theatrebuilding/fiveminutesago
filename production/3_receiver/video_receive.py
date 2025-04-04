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
        self.fallback_active = False
        self.primary_data_received = False

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
        
        # Build the pipeline with two branches feeding into an input-selector:
        # Primary branch: SRT stream.
        # Fallback branch: videotestsrc.
        # We name the last queue in the primary branch "primary_queue" so we can attach a pad probe.
        pipeline_str = f"""
            input-selector name=selector ! kmssink sync=false
            srtsrc uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100"
                ! queue max-size-time=2000000000 max-size-buffers=500 
                ! tsdemux name=demux 
                demux. ! queue ! h264parse config-interval=1 
                ! avdec_h264 
                ! videoconvert 
                ! videoscale 
                ! video/x-raw,width=1920,height=1080 
                ! queue name=primary_queue ! selector.
            videotestsrc pattern=ball 
                ! videoconvert 
                ! videoscale 
                ! video/x-raw,width=1920,height=1080 
                ! queue ! selector.
        """
        return pipeline_str.strip()

    def primary_buffer_probe(self, pad, info):
        # This callback is called whenever a buffer passes through the primary branch.
        if info.type == Gst.PadProbeType.BUFFER:
            if not self.primary_data_received:
                print("VideoReceiver: Primary branch is receiving data.")
            self.primary_data_received = True
        return Gst.PadProbeReturn.OK

    def check_primary_data(self):
        # Called after a timeout to verify if the primary branch is active.
        if not self.primary_data_received and not self.fallback_active:
            print("VideoReceiver: No data from primary source detected, switching to fallback.")
            self.switch_to_fallback()
        # Return False to remove the timeout callback.
        return False

    def switch_to_fallback(self):
        if self.fallback_active:
            # Already switched.
            return
        selector = self.pipeline.get_by_name("selector")
        if not selector:
            print("VideoReceiver: Input-selector not found!")
            return

        # List all sink pads on the selector.
        sink_pads = selector.sinkpads
        if len(sink_pads) < 2:
            print("VideoReceiver: Not enough sink pads on input-selector to switch!")
            return

        # By construction, the second sink pad (index 1) comes from the fallback branch.
        fallback_pad = sink_pads[1]
        selector.set_property("active-pad", fallback_pad)
        self.fallback_active = True
        print("VideoReceiver: Switched to fallback video source.")

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("VideoReceiver: End of Stream")
            # Optionally, switch to fallback when EOS is detected.
            self.switch_to_fallback()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"VideoReceiver: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.switch_to_fallback()

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
            
        # Set up bus message monitoring.
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        # Set the active pad of the input-selector to the primary branch.
        selector = self.pipeline.get_by_name("selector")
        if selector:
            sink_pads = selector.sinkpads
            if sink_pads:
                selector.set_property("active-pad", sink_pads[0])
                print("VideoReceiver: Primary video source active.")

        # Attach a pad probe to the primary branch to detect data flow.
        primary_queue = self.pipeline.get_by_name("primary_queue")
        if primary_queue:
            pad = primary_queue.get_static_pad("src")
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, self.primary_buffer_probe)
        
        # Schedule a timeout to check for data from the primary source after 5 seconds.
        GLib.timeout_add_seconds(5, self.check_primary_data)

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

    # Setup signal handling for graceful shutdown.
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))

    receiver.run()

if __name__ == "__main__":
    Gst.init(None)
    main()
