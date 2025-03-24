#!/usr/bin/env python3
"""
Video Send Script (using gst-launch-1.0 directly, without Gst.parse_launch)
Run with:
  python3 video_send.py --device hw:0,0 --country tn
  python3 video_send.py --device hw:0,0 --country dk
"""

import os
import sys
import signal
import argparse
import subprocess

# 1) Insert parent directory into Python path, so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

def main():
    # Use argparse to capture device and country (even if device isn’t used for video,
    # it is passed in for consistency)
    parser = argparse.ArgumentParser(description="Video Send Script (shell-based)")
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
    config_interval = video_opts.get("config_interval", 1)

    # Convert Python bools to GStreamer string booleans
    aud_str = "true" if aud_bool else "false"
    byte_stream_str = "true" if byte_stream else "false"

    # Construct the pipeline using these config values
    pipeline_str = (
        f"gst-launch-1.0 -v "
        f"{video_source} "
        f"! videoconvert "
        f"! videoscale "
        f"! video/x-raw,width=1920,height=1080 "  # Set the desired dimensions here
        f"! {video_encoder} bitrate={bitrate} tune={tune} key-int-max={key_int_max} bframes={bframes} aud={aud_str} byte-stream={byte_stream_str} "
        f"! video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline "
        f"! h264parse config-interval={config_interval} "
        f"! queue "
        f"! mpegtsmux alignment={alignment} "
        f"! srtsink uri='srt://{server_ip}:{video_send_port}?mode=caller&{streaming_settings}'"
    )

    print("Pipeline command:\n", pipeline_str)

    # Launch gst-launch as a subprocess
    process = subprocess.Popen(pipeline_str, shell=True)

    # Define signal handler to gracefully stop gst-launch
    def signal_handler(sig, frame):
        print("Stopping pipeline...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for gst-launch to finish
    return_code = process.wait()
    if return_code != 0:
        print(f"gst-launch-1.0 exited with code {return_code}")

if __name__ == "__main__":
    main()