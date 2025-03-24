#!/usr/bin/env python3
# Run with:
# python3 receive.py --device hw:0,0 --country tn
# python3 receive.py --device hw:0,0 --country dk
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal
import sys
import argparse

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

    # Parse command-line arguments to get the country code and device
    parser = argparse.ArgumentParser(description="Receiver Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    parser.add_argument("--device", required=True, help="Device to use")
    args = parser.parse_args()

    # Build each part of the pipeline (audio + video) using the provided parameters.
    # The build_audio_pipeline and build_video_pipeline functions should use these values
    # to decide which port (e.g., 'audio_receive' vs 'audio_receive2') to use and which device.
    audio_part = build_audio_pipeline(args.country, args.device)
    video_part = build_video_pipeline(args.country, args.device)

    print("Audio part:", audio_part)
    print("Video part:", video_part)
    
    # Combine them into one pipeline string.
    pipeline_str = f"""
        {audio_part}
        {video_part}
    """.strip()
    
    print("Receiver: Final pipeline:\n", pipeline_str, "\n")
    
    # Parse and launch the pipeline
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
