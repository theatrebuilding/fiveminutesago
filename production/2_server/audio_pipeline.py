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
audio_send_port     = cfg.get("ports", {}).get("audio_send")
audio_send_port2    = cfg.get("ports", {}).get("audio_send2")
audio_receive_port  = cfg.get("ports", {}).get("audio_receive")
audio_receive_port2 = cfg.get("ports", {}).get("audio_receive2")
streaming_settings  = cfg.get("streaming_settings_audio", "")
clock_rate          = cfg.get("audio", {}).get("rate", 32000)
channels            = cfg.get("audio", {}).get("channels", 2)
encoding_name       = cfg.get("audio", {}).get("encoding_name", "L16")

def build_audio_pipeline():
    pipeline = f"""
    gst-launch-1.0 -v \\
        srtsrc uri=srt://:{audio_send_port}?mode=listener&{streaming_settings}
            ! queue
            ! application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels}
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! queue
            ! mixer.

        
        srtsrc uri=srt://:{audio_send_port2}?mode=listener&{streaming_settings}
            ! queue
            ! application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels}
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! queue
            ! mixer.

        
        multifilesrc location="/mnt/usb/Haut_Recs/ordered/multifile_%04d.mp3" index=0 loop=true
            ! decodebin
            ! audioconvert
            ! audioresample
            ! volume name=multivol volume=0.0
            ! queue
            ! mixer.
        
        
        audiomixer name=mixer
            ! audioconvert
            ! audioresample
            ! audio/x-raw,format=S16BE,channels=2,rate=32000
            ! tee name=t

        
        t. ! queue
            ! rtpL16pay
            ! srtsink uri=srt://:{audio_receive_port}?mode=listener wait-for-connection=false

        
        t. ! queue
            ! rtpL16pay
            ! srtsink uri=srt://:{audio_receive_port2}?mode=listener wait-for-connection=false

        
        t. ! queue
            ! audioconvert
            ! audioresample
            ! lamemp3enc bitrate=128
            ! shout2send
                ip=s40.myradiostream.com
                port=23058
                mount=/stream
                password=5e4ThU3VW
    """
    return "gst-launch-1.0 -v " + pipeline.strip()

if __name__ == "__main__":
    print("Audio Pipeline:")
    print(build_audio_pipeline())
