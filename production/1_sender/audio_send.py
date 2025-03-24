#!/usr/bin/env python3
import os
import sys
import time
import signal
import subprocess
import argparse

# 1) Insert the parent folder into sys.path so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

def run_command(command):
    """Runs a shell command as a subprocess and returns the process."""
    return subprocess.Popen(command, shell=True, preexec_fn=os.setsid)

def stop_process(process):
    """Stops the subprocess gracefully."""
    if process:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

def main():
    # Use argparse to get the device and country from the main script
    parser = argparse.ArgumentParser(description="Audio Send Script")
    parser.add_argument("--device", required=True, help="Audio device to use (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    config = load_config()

    # Validate required keys in config
    if "server_ip" not in config:
        print("ERROR: 'server_ip' key not found in config.yaml. Please define it.")
        sys.exit(1)

    if "ports" not in config:
        print("ERROR: 'ports' section not found in config.yaml. Please define it.")
        sys.exit(1)

    # Choose the audio send port based on the country
    if args.country.lower() == "tn":
        audio_send_port = config["ports"].get("audio_send")
    else:
        audio_send_port = config["ports"].get("audio_send2")

    server_ip = config["server_ip"]
    streaming_settings = config.get("streaming_settings_audio", "")
    source = config.get("audio", {}).get("source", "autoaudiosrc")
    audio_format = config.get("audio", {}).get("format", "S16BE")
    audio_channels = config.get("audio", {}).get("channels", 2)
    audio_rate = config.get("audio", {}).get("rate", 32000)
    
    # Use the device value provided by the main script
    device = args.device

    # Build the GStreamer command for sending audio
    send_audio_cmd = (
        f"gst-launch-1.0 -v {source} device={device} ! "
        f"audioconvert ! audioresample ! "
        f"audio/x-raw,channels=1,rate=32000 ! audioconvert ! audio/x-raw,channels=2,rate=32000 ! "
        f"rtpL16pay ! "
        f"srtsink uri='srt://{server_ip}:{audio_send_port}?mode=caller&{streaming_settings}'"
    )

    print("Starting audio sending pipeline...")
    print(f"Host: {server_ip}, Port: {audio_send_port}")

    send_process = None

    def signal_handler(sig, frame):
        print("\nStopping audio sending pipeline...")
        stop_process(send_process)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        send_process = run_command(send_audio_cmd)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
