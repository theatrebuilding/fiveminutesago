#!/usr/bin/env python3
import os
import sys
import signal
import argparse

# 1) Insert parent directory into Python path, so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

Gst.init(None)
loop = None

def on_message(bus, message):
    if message.type == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        print(f"GStreamer ERROR: {err}, debug: {dbg}")
        if loop:
            loop.quit()
    elif message.type == Gst.MessageType.EOS:
        print("End-of-stream reached.")
        if loop:
            loop.quit()

def signal_handler(sig, frame, pipeline):
    print("Stopping pipeline...")
    pipeline.set_state(Gst.State.NULL)
    if loop:
        loop.quit()

def main():
    # Use argparse to capture device and country (even if device isn’t used for video, it is passed in for consistency)
    parser = argparse.ArgumentParser(description="Video Send Script")
    parser.add_argument("--device", required=True, help="Audio device to use (if applicable)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    # Load config
    cfg = load_config()
    if "server_ip" not in cfg:
        print("ERROR: 'server_ip' key not found in config.yaml. Please define it.")
        sys.exit(1)
    if "ports" not in cfg:
        print("ERROR: 'ports' section not found in config.yaml. Please define it.")
        sys.exit(1)

    # Choose the video send port based on the country
    if args.country.lower() == "tn":
        video_send_port = cfg["ports"].get("video_send")
    else:
        video_send_port = cfg["ports"].get("video_send2")

    server_ip = cfg.get("server_ip")
    streaming_settings = cfg.get("streaming_settings_video", "")

    # Read video-specific configs
    video_opts = cfg.get("video", {})
    video_source = video_opts.get("source", "/dev/video0")
    bitrate = video_opts.get("bitrate", 1000)
    key_int_max = video_opts.get("key_int_max", 15)
    tune = video_opts.get("tune", "zerolatency")
    video_encoder = video_opts.get("encoder", "x264enc")
    alignment = video_opts.get("alignment", "nal")
    bframes = video_opts.get("bframes", 0)
    aud_bool = video_opts.get("aud", True)
    byte_stream = video_opts.get("byte_stream", True)
    option_str = video_opts.get("option_str", "")
    config_interval = video_opts.get("config_interval", 1)

    aud_str = "true" if aud_bool else "false"
    byte_stream_str = "true" if byte_stream else "false"

    # Construct the pipeline using these config values
    pipeline_str = (
        f"{video_source} "
        f"! videoconvert "
        f"! {video_encoder} bitrate={bitrate} tune={tune} key-int-max={key_int_max} bframes={bframes} aud={aud_str} byte-stream={byte_stream_str} option-string={option_str}
        f"! video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline "
        f"! h264parse config-interval={config_interval} "
        f"! queue "
        f"! mpegtsmux alignment={alignment} "
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
