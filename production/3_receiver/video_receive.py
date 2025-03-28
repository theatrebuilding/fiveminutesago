#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib, cairo  # Import cairo from gi.repository
import os
import sys
import signal
import argparse
import math  # For math.pi

# Import the configuration loader
from config_loader import load_config

class VideoReceiver:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_address = None
        self.receive_port = None
        # Overlay state for storing video dimensions and validity.
        self.overlay_state = {"valid": False, "width": 0, "height": 0}

    def build_pipeline(self):
        """
        Build the GStreamer pipeline string for receiving video.
        This pipeline uses the live SRT stream, demuxes it, decodes it,
        overlays a circle using cairooverlay on a transparent surface,
        and displays it.
        """
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
                ! cairooverlay name=overlay draw-on-transparent-surface=true
                ! kmssink sync=false
        """
        return pipeline_str.strip()

    @staticmethod
    def caps_changed_callback(overlay, caps, user_data):
        """
        Callback for the 'caps-changed' signal.
        Parses the Gst.Caps to update the overlay state with video dimensions.
        """
        structure = caps.get_structure(0)
        success_width, width = structure.get_int("width")
        success_height, height = structure.get_int("height")
        if success_width and success_height:
            user_data["width"] = width
            user_data["height"] = height
            user_data["valid"] = True
            print(f"Overlay caps changed: width={width}, height={height}")

    @staticmethod
    def draw_callback(overlay, cr, timestamp, duration, user_data):
        """
        Callback for the 'draw' signal.
        Draws a black circle on a transparent surface.
        """
        if not user_data.get("valid", False):
            return

        # For demonstration, we use fixed coordinates.
        # You may update these to be dynamic based on user input or video dimensions.
        x, y = 150, 100  # Center coordinates in pixels
        radius = 30      # Radius in pixels

        # Use the Cairo context methods to draw a circle.
        cr.set_source_rgba(0, 0, 0, 1)  # Black, fully opaque
        cr.arc(x, y, radius, 0, 2 * math.pi)
        cr.fill()

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
        Parse the pipeline string, set up the bus watch, connect the overlay callbacks,
        and run the main loop.
        """
        pipeline_str = self.build_pipeline()
        print("VideoReceiver: Pipeline:\n", pipeline_str, "\n")

        self.pipeline = Gst.parse_launch(pipeline_str)
        
        # Retrieve the cairooverlay element and connect both callbacks.
        overlay = self.pipeline.get_by_name("overlay")
        if overlay:
            overlay.connect("draw", self.draw_callback, self.overlay_state)
            overlay.connect("caps-changed", self.caps_changed_callback, self.overlay_state)
        else:
            print("VideoReceiver: cairooverlay element not found in the pipeline.")

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
    parser = argparse.ArgumentParser(description="Video Receiver Script")
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
