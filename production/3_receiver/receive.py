#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal
import sys

# Import the pipeline builders
from audio_receive import build_audio_pipeline
from video_receive import build_video_pipeline

Gst.init(None)
loop = None

def on_message(bus, message):
    t = message.type
    if t == Gst.MessageType.EOS:
        print("Receiver: End of Stream")
        loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Receiver: ERROR -> {err}")
        if debug:
            print(f"Debug info: {debug}")
        loop.quit()

def signal_handler(sig, frame):
    print("Receiver: Interrupt received, stopping pipeline...")
    if loop is not None:
        loop.quit()

def main():
    global loop
    
    # Build each part of the pipeline (audio + video)
    audio_part = build_audio_pipeline()
    video_part = build_video_pipeline()
    
    # Combine them into one pipeline string
    pipeline_str = f"""
        {audio_part}
        {video_part}
    """
    
    print("Receiver: Final pipeline:\n", pipeline_str, "\n")
    
    # Parse and launch
    pipeline = Gst.parse_launch(pipeline_str)
    
    # Set up bus to monitor for messages
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)
    
    # Start playing
    pipeline.set_state(Gst.State.PLAYING)
    
    # Main loop
    loop = GLib.MainLoop()
    
    # Handle Ctrl+C / kill signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Receiver: Pipeline stopped.")

if __name__ == "__main__":
    main()
