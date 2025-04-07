#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import sys
import signal
import argparse
import time

from config_loader import load_config

class VideoReceiver:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_address = None
        self.receive_port = None
        # True if fallback is active; false if primary is active.
        self.fallback_active = False
        # Last time (seconds) a buffer was seen on the primary monitor branch.
        self.last_primary_buffer_time = None
        # Timeout threshold (seconds) after which primary is considered down.
        self.primary_timeout_threshold = 5
        self.clock = None

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")
        
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
                ! queue name=primary_in
                ! tee name=primary_tee
                primary_tee. ! queue name=primary_selector ! selector.
                primary_tee. ! queue name=primary_monitor ! fakesink sync=false async=false
            videotestsrc pattern=ball
                ! videoconvert
                ! videoscale
                ! video/x-raw,width=1920,height=1080
                ! queue ! selector.
        """
        return pipeline_str.strip()

    def primary_buffer_probe(self, pad, info):
        # Called whenever a buffer flows on the primary_monitor branch.
        if info.type & Gst.PadProbeType.BUFFER:
            self.last_primary_buffer_time = time.monotonic()
        return Gst.PadProbeReturn.OK

    def monitor_primary(self):
        """Check periodically if the primary branch is healthy.
           Only print when a switch occurs.
        """
        now = time.monotonic()
        primary_healthy = (self.last_primary_buffer_time is not None and
                           (now - self.last_primary_buffer_time) < self.primary_timeout_threshold)
        
        if primary_healthy and self.fallback_active:
            print("VideoReceiver: Primary stream recovered; switching to primary.")
            self.switch_to_primary()
        elif not primary_healthy and not self.fallback_active:
            print("VideoReceiver: Primary stream down; switching to fallback.")
            self.switch_to_fallback()
        # Do not print status if already in the correct state.
        return True  # Continue the timeout callback

    def switch_to_primary(self):
        selector = self.pipeline.get_by_name("selector")
        if not selector:
            return
        sink_pads = selector.sinkpads
        if not sink_pads:
            return
        # Assume primary branch is connected to the first sink pad.
        selector.set_property("active-pad", sink_pads[0])
        self.fallback_active = False

    def switch_to_fallback(self):
        selector = self.pipeline.get_by_name("selector")
        if not selector:
            return
        sink_pads = selector.sinkpads
        if len(sink_pads) < 2:
            return
        # Assume fallback branch is connected to the second sink pad.
        selector.set_property("active-pad", sink_pads[1])
        self.fallback_active = True

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            print("VideoReceiver: End of Stream")
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"VideoReceiver: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")

    def run(self):
        pipeline_str = self.build_pipeline()
        print("VideoReceiver: Pipeline:\n", pipeline_str, "\n")
        self.pipeline = Gst.parse_launch(pipeline_str)
        
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        
        # Set initial active pad to primary branch.
        selector = self.pipeline.get_by_name("selector")
        if selector and selector.sinkpads:
            selector.set_property("active-pad", selector.sinkpads[0])
            self.fallback_active = False
            print("VideoReceiver: Starting with primary video source.")
        else:
            print("VideoReceiver: Could not set initial active pad.")
        
        # Attach pad probe to the 'primary_monitor' queue's src pad.
        primary_monitor_queue = self.pipeline.get_by_name("primary_monitor")
        if primary_monitor_queue:
            pad = primary_monitor_queue.get_static_pad("src")
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, self.primary_buffer_probe)
            else:
                print("VideoReceiver: Could not get src pad on primary_monitor.")
        else:
            print("VideoReceiver: primary_monitor element not found!")
        
        # Set up a periodic timer (every 2 seconds) to monitor primary health.
        GLib.timeout_add_seconds(2, self.monitor_primary)
        
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
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))
    receiver.run()

if __name__ == "__main__":
    Gst.init(None)
    main()
