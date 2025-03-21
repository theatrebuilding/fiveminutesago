#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib
# from modules.timed_volume import setup_dynamic_volume_control # Import the volume control timing function.
from modules.create_symlinks import create_sequential_symlinks # Import the function to create symlinks so that gstreamer can play the audio files.

import signal
import sys

# Import the pipeline builders.
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

    # Build the audio and video pipeline strings.
    # These functions fetch port values from the config file.
    audio_part = build_audio_pipeline()
    video_part = build_video_pipeline()

    # Combine the parts into one final pipeline string.
    pipeline_str = f"""
{audio_part}
{video_part}
    """

    print("Pipeline:\n", pipeline_str, "\n")

    # Create the pipeline from the combined string.
    pipeline = Gst.parse_launch(pipeline_str)

    # Set up dynamic volume control using the gstcontroller-based mechanism.
    # volume_elem = pipeline.get_by_name("multivol")
    # if volume_elem:
    #     setup_dynamic_volume_control(volume_elem)
    # else:
    #     print("Volume element 'multivol' not found!")

    # Set up bus watch.
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)

    # Start playing.
    pipeline.set_state(Gst.State.PLAYING)

    # Main loop.
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
