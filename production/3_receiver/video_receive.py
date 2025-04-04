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
        self.fallback_active = False
        # Time (in seconds) when the last primary buffer was seen.
        self.last_primary_buffer_time = None
        # If no buffer has been seen in this many seconds, switch to fallback.
        self.primary_timeout_threshold = 5
        self.clock = None
    
    def set_clock(self, clock):
        self.clock = clock
        print(f"VideoReceiver: Clock set to {clock}.")


    def build_pipeline(self):
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")
        
        # Pipeline description:
        # - The input-selector ("selector") has two branches:
        #   • Primary branch: the SRT stream is decoded and processed.
        #   • Fallback branch: a videotestsrc producing the "ball" pattern.
        # - The primary branch ends in a queue named "primary_queue"
        #   where a pad probe is attached to record when buffers arrive.
        # - The output of the input-selector goes to kmssink.
        pipeline_str = f"""
            input-selector name=selector ! kmssink sync=false
            srtsrc uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100" wait-for-connection=false
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
        # This probe is called whenever a buffer is seen on the primary branch.
        if info.type & Gst.PadProbeType.BUFFER:
            now = time.monotonic()
            if self.last_primary_buffer_time is None:
                print("VideoReceiver: Primary branch started receiving data.")
            self.last_primary_buffer_time = now
        return Gst.PadProbeReturn.OK

    def monitor_primary(self):
        """Periodically check the primary branch.
           - If no buffer has been seen for longer than the threshold and
             we're not in fallback, switch to fallback.
           - If buffers are being received and we're in fallback, switch back.
        """
        now = time.monotonic()
        primary_is_healthy = (
            self.last_primary_buffer_time is not None and
            (now - self.last_primary_buffer_time) < self.primary_timeout_threshold
        )
        
        if primary_is_healthy and self.fallback_active:
            print("VideoReceiver: Primary stream recovered; switching back to primary.")
            self.switch_to_primary()
        elif not primary_is_healthy and not self.fallback_active:
            print("VideoReceiver: Primary stream appears down; switching to fallback.")
            self.switch_to_fallback()
        else:
            if self.fallback_active:
                print("VideoReceiver: Still in fallback mode; primary stream not healthy yet.")
            else:
                print("VideoReceiver: Primary stream healthy; continuing with primary.")
        return True  # Continue calling this timeout callback

    def switch_to_primary(self):
        selector = self.pipeline.get_by_name("selector")
        if not selector:
            print("VideoReceiver: Input-selector not found!")
            return
        sink_pads = selector.sinkpads
        if not sink_pads:
            print("VideoReceiver: No sink pads found on input-selector!")
            return

        # Assume the primary branch is connected to the first sink pad.
        primary_pad = sink_pads[0]
        selector.set_property("active-pad", primary_pad)
        self.fallback_active = False
        print("VideoReceiver: Switched to primary video source.")

    def switch_to_fallback(self):
        selector = self.pipeline.get_by_name("selector")
        if not selector:
            print("VideoReceiver: Input-selector not found!")
            return
        sink_pads = selector.sinkpads
        if len(sink_pads) < 2:
            print("VideoReceiver: Not enough sink pads on input-selector to switch!")
            return

        # Assume the fallback branch is connected to the second sink pad.
        fallback_pad = sink_pads[1]
        selector.set_property("active-pad", fallback_pad)
        self.fallback_active = True
        print("VideoReceiver: Switched to fallback video source.")

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
        if selector:
            sink_pads = selector.sinkpads
            if sink_pads:
                selector.set_property("active-pad", sink_pads[0])
                print("VideoReceiver: Starting with primary video source.")
            else:
                print("VideoReceiver: No sink pads available in input-selector.")

        # Attach a pad probe to the primary branch queue to track buffer arrival.
        primary_queue = self.pipeline.get_by_name("primary_queue")
        if primary_queue:
            pad = primary_queue.get_static_pad("src")
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, self.primary_buffer_probe)
            else:
                print("VideoReceiver: Could not get src pad on primary_queue.")
        else:
            print("VideoReceiver: primary_queue not found!")

        # Set up a periodic timer (every 2 seconds) to monitor the primary stream.
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
