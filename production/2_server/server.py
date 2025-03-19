#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal
import sys

from audio_pipeline import build_audio_pipeline
from video_pipeline import build_video_pipeline

Gst.init(None)
loop = None

def on_message(bus, message):
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        print("End of stream.")
        loop.quit()
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"ERROR: {err}, Debug info: {debug}")
        loop.quit()

def signal_handler(sig, frame):
    print("Interrupt received, stopping pipeline...")
    if loop:
        loop.quit()

def main():
    global loop

    # Build the audio and video pipeline strings
    audio_part = build_audio_pipeline()
    video_part = build_video_pipeline()

    # Combine them into one final pipeline string
    pipeline_str = f"""
        {audio_part}
        {video_part}
    """

    print("Pipeline:\n", pipeline_str, "\n")

    # Create the pipeline from the combined string
    pipeline = Gst.parse_launch(pipeline_str)

    # Set up bus watch
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)

    # Start playing
    pipeline.set_state(Gst.State.PLAYING)

    # Main loop
    loop = GLib.MainLoop()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")

if __name__ == "__main__":
    main()
