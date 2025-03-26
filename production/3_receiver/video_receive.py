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

    config = load_config()
    server_address = config.get("server_ip")
    streaming_settings = config.get("streaming_settings_video", "")
    image_height = config.get("video", {}).get("height", 1080)
    image_width = config.get("video", {}).get("width", 1920)
    framerate = config.get("video", {}).get("framerate", 25)
    
    # Choose the video receive port based on the country.
    if country.lower() == "tn":
        receive_port = config.get("ports", {}).get("video_receive_tn")
    else:
        receive_port = config.get("ports", {}).get("video_receive_dk")
    
    pipeline = (
        f'srtsrc uri="srt://{server_address}:{receive_port}?mode=caller" '
        f'! queue max-size-time=2000000000 max-size-buffers=500 '
        f'! tsdemux name=demux '
        f'demux. ! queue '
        f'! h264parse config-interval=1 '
        f'! avdec_h264 '
        f'! videoconvert '
        f'! videoscale '
        f'! video/x-raw,width={image_width},height={image_height},framerate={framerate}/1 '
        f'! kmssink sync=false'
    )
    return pipeline.strip()

if __name__ == "__main__":
    # For testing purposes:
    print(build_video_pipeline("tn", "unused"))
