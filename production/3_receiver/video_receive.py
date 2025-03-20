#!/usr/bin/env python3
import os
import sys

# Insert parent directory for config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

def build_video_pipeline(country, device):
    """
    Build the GStreamer pipeline string for receiving video.
    
    Parameters:
      country (str): Used to choose the correct receive port.
      device (str): Not used in video pipeline; included for consistency.
    """
    config = load_config()
    server_address = config.get("server_ip")
    
    # Choose the video receive port based on the country.
    if country.lower() == "tn":
        receive_port = config.get("ports", {}).get("video_receive")
    else:
        receive_port = config.get("ports", {}).get("video_receive2")
    
    pipeline = f"""
        srtsrc uri="srt://{server_address}:{receive_port}?mode=caller"
            ! queue 
            ! tsdemux 
            ! h264parse 
            ! avdec_h264 
            ! videoconvert 
            ! autovideosink
    """
    return pipeline.strip()

if __name__ == "__main__":
    # For testing purposes:
    print(build_video_pipeline("tn", "unused"))
