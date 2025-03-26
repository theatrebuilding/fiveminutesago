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
    
    # Choose the audio receive port based on the country.
    if country.lower() == "tn":
        receive_port = config.get("ports", {}).get("audio_receive_tn")
    else:
        receive_port = config.get("ports", {}).get("audio_receive_dk")
    
    pipeline = f"""
        srtsrc uri="srt://{server_address}:{receive_port}?mode=caller&latency=1000&maxbw=0"
            ! tee name=t
            ! queue max-size-time=200000000
            ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! alsasink device="{device}"

        t. ! queue
            ! audioconvert 
            ! audioresample 
            ! audio/x-raw,channels=1,rate=32000 
            ! rtpL16pay 
            ! srtsink uri="srt://:8819?mode=listener&latency=10" wait-for-connection=false 
    """
    return pipeline.strip()

if __name__ == "__main__":
    # For testing purposes:
    print(build_audio_pipeline("tn", "hw:0,0"))

