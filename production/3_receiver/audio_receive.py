#!/usr/bin/env python3
import os
import sys

# Insert parent directory for config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

def build_audio_pipeline(country, device):

    config = load_config()
    server_address = config.get("server_ip", "127.0.0.1")
    streaming_settings = config.get("streaming_settings_audio", "")
    audio_rate = config.get("audio", {}).get("rate", 32000)
    encoding_name = config.get("audio", {}).get("encoding_name", "L16")
    
    # Choose the audio receive port based on the country.
    if country.lower() == "tn":
        receive_port = config.get("ports", {}).get("audio_receive_tn")
    else:
        receive_port = config.get("ports", {}).get("audio_receive_dk")
    
    pipeline = f"""
        srtsrc uri="srt://{server_address}:{receive_port}?mode=caller&{streaming_settings}"
            ! queue max-size-time=200000000
            ! application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels=2
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! alsasink device="{device}"

    """
    return pipeline.strip()

if __name__ == "__main__":
    # For testing purposes:
    print(build_audio_pipeline("tn", "hw:0,0"))

