#!/usr/bin/env python3
import os
import sys

# 1) Insert parent directory into Python path so we can import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Now we can import the loader.
from config_loader import load_config

# 3) Load config.
cfg = load_config()

# General config values.
video_send_tn = cfg.get("ports", {}).get("video_send_tn")
video_send_dk = cfg.get("ports", {}).get("video_send_dk")
video_receive_dk = cfg.get("ports", {}).get("video_receive_dk")
video_receive_tn = cfg.get("ports", {}).get("video_receive_tn")
streaming_settings = cfg.get("streaming_settings_video", {})

recorded_file_tn = "/mnt/tbdrive/video_tn.ts"
recorded_file_dk = "/mnt/tbdrive/video_dk.ts"

def build_video_pipeline():
    # These pipelines relay the stream between ports with low latency and bounded buffering.
    pipeline1 = (
        f'srtsrc name=v_send_tn uri="srt://:{video_send_tn}?mode=listener" '
        f'! queue max-size-time=5000000000 max-size-buffers=500 '
        f'! tee name=tee_tn '
        f' tee_tn. ! queue ! srtsink name=v_recv_dk uri="srt://:{video_receive_dk}?mode=listener"'  
        f' tee_tn. ! queue ! filesink location="{recorded_file_tn}" '
    )
    pipeline2 = (
        f'srtsrc name=v_send_dk uri="srt://:{video_send_dk}?mode=listener" '
        f'! queue max-size-time=5000000000 max-size-buffers=500 '
        f'! tee name=tee_dk '
        f' tee_dk. ! queue ! srtsink name=v_recv_tn uri="srt://:{video_receive_tn}?mode=listener"'
        f' tee_dk. ! queue ! filesink location="{recorded_file_dk}" '
    )
    return pipeline1, pipeline2

if __name__ == "__main__":
    pipelines = build_video_pipeline()
    print("Video Pipeline 1:")
    print(pipelines[0])
    print("\nVideo Pipeline 2:")
    print(pipelines[1])
