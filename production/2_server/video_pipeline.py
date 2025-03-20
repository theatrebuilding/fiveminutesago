"""
Put comments here
"""

import os
import sys

# 1) Insert parent directory into Python path, so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Now we can import the loader
from config_loader import load_config

# 3) Load config
cfg = load_config()

# General config values
video_send_port = cfg.get("ports", {}).get("video_send")
video_send_port2 = cfg.get("ports", {}).get("video_send2")
video_receive_port = cfg.get("ports", {}).get("video_receive")
video_receive_port2 = cfg.get("ports", {}).get("video_receive2")
streaming_settings = cfg.get("streaming_settings_video", {})


def build_video_pipeline():
    return f"""
gst-launch-1.0 -v \\
    ( srtsrc uri="srt://:{video_send_port}?mode=listener" ! queue ! srtsink uri="srt://:{video_receive_port}?mode=listener" ) \\
    ( srtsrc uri="srt://:{video_send_port2}?mode=listener" ! queue ! srtsink uri="srt://:{video_receive_port2}?mode=listener" )
"""


