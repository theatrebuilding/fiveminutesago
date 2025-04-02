#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib

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
    print("Interrupt received, stopping pipelines...")
    if loop:
        loop.quit()

def main():
    global loop

    # Build the audio and video pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Returns a tuple (video_pipeline1, video_pipeline2)

    print("Audio Pipeline:\n", audio_pipeline_str, "\n")
    print("Video Pipeline 1:\n", video_pipeline_strs[0], "\n")
    print("Video Pipeline 2:\n", video_pipeline_strs[1], "\n")

    # Create separate pipeline objects.
    audio_pipeline = Gst.parse_launch(audio_pipeline_str)
    video_pipeline1 = Gst.parse_launch(video_pipeline_strs[0])
    video_pipeline2 = Gst.parse_launch(video_pipeline_strs[1])

    # Set up bus watch for each pipeline.
    for pipeline in (audio_pipeline, video_pipeline1, video_pipeline2):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message)

    # Start playing all pipelines.
    audio_pipeline.set_state(Gst.State.PLAYING)
    video_pipeline1.set_state(Gst.State.PLAYING)
    video_pipeline2.set_state(Gst.State.PLAYING)

    # Main loop.
    loop = GLib.MainLoop()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        loop.run()
    finally:
        # Clean up.
        audio_pipeline.set_state(Gst.State.NULL)
        video_pipeline1.set_state(Gst.State.NULL)
        video_pipeline2.set_state(Gst.State.NULL)
        print("Pipelines stopped.")

if __name__ == "__main__":
    main()
