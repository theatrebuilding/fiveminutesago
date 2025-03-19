#!/usr/bin/env python3
import os
import sys
import time
import signal
import subprocess

# 1) Insert the parent folder into sys.path so we can import config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Now we can import load_config
from config_loader import load_config

def ask_for_device():
    """Asks the user for the audio device to use."""
    print("Please enter the audio device to use:")
    print("Example: alsasrc device=hw:0,0")
    return input("Device: ")

def run_command(command):
    """Runs a shell command as a subprocess and returns the process."""
    return subprocess.Popen(command, shell=True, preexec_fn=os.setsid)

def stop_process(process):
    """Stops the subprocess gracefully."""
    if process:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

def main():
    config = load_config()

    # Validate the keys we'll use
    if "server_ip" not in config:
        print("ERROR: 'server_ip' key not found in config.yaml. Please define it.")
        sys.exit(1)

    if "ports" not in config or "audio_send" not in config["ports"]:
        print("ERROR: 'ports.audio_send' not found in config.yaml. Please define it.")
        sys.exit(1)

    server_ip = config["server_ip"]
    streaming_settings = config["streaming_settings"]
    audio_send_port = config["ports"]["audio_send"]
    source = config.get("audio", {}).get("source", "autoaudiosrc")
    audio_format = config.get("audio", {}).get("format", "S16BE")
    audio_channels = config.get("audio", {}).get("channels", 2)
    audio_rate = config.get("audio", {}).get("rate", 32000)
    device = ask_for_device()

    # Build the GStreamer command for sending audio
    send_audio_cmd = (
        f"gst-launch-1.0 -v {source} {device} ! "
        f"audioconvert ! audioresample ! "
        f"audio/x-raw,format={audio_format},channels={audio_channels},rate={audio_rate} ! "
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

    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start sending audio
        send_process = run_command(send_audio_cmd)

        # Keep the script alive while the subprocess runs
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
