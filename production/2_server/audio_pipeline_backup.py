#!/usr/bin/env python3
import os
import sys

# 1) Insert parent directory into Python path so we can import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Import the configuration loader and load config.
from config_loader import load_config
cfg = load_config()

# 3) Fetch port values and streaming settings from the config.
audio_send_tn     = cfg.get("ports", {}).get("audio_send_tn")
audio_send_dk    = cfg.get("ports", {}).get("audio_send_dk")
audio_receive_dk  = cfg.get("ports", {}).get("audio_receive_dk")
audio_receive_tn = cfg.get("ports", {}).get("audio_receive_tn")
streaming_settings  = cfg.get("streaming_settings_audio", "")
clock_rate          = cfg.get("audio", {}).get("rate", 32000)
channels            = cfg.get("audio", {}).get("channels", 2)
encoding_name       = cfg.get("audio", {}).get("encoding_name", "L16")

def build_audio_pipeline():
    pipeline = f"""
        srtsrc uri=srt://:{audio_send_tn}?mode=listener&latency=100 !
          queue !
          application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          audioconvert !
          audioresample !
          tee name=tee_tn

        tee_tn. ! queue !
          rtpL16pay !
          srtsink uri=srt://:{audio_receive_dk}?mode=listener wait-for-connection=false

        srtsrc uri=srt://:{audio_send_dk}?mode=listener&latency=100 !
          queue !
          application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          audioconvert !
          audioresample !
          tee name=tee_dk

        tee_dk. ! queue !
          rtpL16pay !
          srtsink uri=srt://:{audio_receive_tn}?mode=listener wait-for-connection=false

   
    """
    return pipeline.strip()


if __name__ == "__main__":
    print("Audio Pipeline:")
    print(build_audio_pipeline())
