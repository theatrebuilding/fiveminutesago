#!/usr/bin/env python3
import os
import sys

# 1) Insert parent directory into Python path, so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Now we can import the loader
from config_loader import load_config

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal

Gst.init(None)
loop = None

def on_message(bus, message):
    if message.type == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        print(f"GStreamer ERROR: {err}, debug: {dbg}")
        if loop: loop.quit()
    elif message.type == Gst.MessageType.EOS:
        print("End-of-stream reached.")
        if loop: loop.quit()

def signal_handler(sig, frame, pipeline):
    print("Stopping pipeline...")
    pipeline.set_state(Gst.State.NULL)
    if loop: loop.quit()

def main():
    # 3) Load config
    cfg = load_config()

    # General config values
    server_ip = cfg.get("server_ip")
    video_send_port = cfg.get("ports", {}).get("video_send")
    streaming_settings = cfg.get("streaming_settings", {})

    # Read any video-specific configs
    video_opts = cfg.get("video", {})
    video_source = video_opts.get("source", "/dev/video0")
    bitrate = video_opts.get("bitrate", 1000)
    key_int_max = video_opts.get("key_int_max", 15)
    tune = video_opts.get("tune", "zerolatency")
    video_encoder = video_opts.get("encoder", "x264enc")

    # Construct the pipeline using these config values
    pipeline_str = (
        f"{video_source} "
        f"! videoconvert ! videorate "
        f"! {video_encoder} bitrate={bitrate} tune={tune} key-int-max={key_int_max} "
        f"! video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline "
        f"! h264parse config-interval=1 "
        f"! queue "
        f"! mpegtsmux alignment=7 "
        f"! srtsink uri='srt://{server_ip}:{video_send_port}?mode=caller&{streaming_settings}'"
    )

    print("Pipeline:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)

    pipeline.set_state(Gst.State.PLAYING)

    global loop
    loop = GLib.MainLoop()

    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, pipeline))
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s, f, pipeline))

    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")

if __name__ == "__main__":
    main()
