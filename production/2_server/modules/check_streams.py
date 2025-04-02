#!/usr/bin/env python3
import subprocess
import time
import logging
import os
import sys

# Insert parent directory to access config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

# Set up logging (if desired).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Load configuration.
cfg = load_config()

# Define endpoints for audio and video.
endpoints_audio = {
    "Sending from Tunisia": cfg.get("ports", {}).get("audio_send_tn"),
    "Sending from Denmark": cfg.get("ports", {}).get("audio_send_dk"),
    "Receiving in Tunisia": cfg.get("ports", {}).get("audio_receive_tn"),
    "Receiving in Denmark": cfg.get("ports", {}).get("audio_receive_dk"),
}

endpoints_video = {
    "Sending from Tunisia": cfg.get("ports", {}).get("video_send_tn"),
    "Sending from Denmark": cfg.get("ports", {}).get("video_send_dk"),
    "Receiving in Tunisia": cfg.get("ports", {}).get("video_receive_tn"),
    "Receiving in Denmark": cfg.get("ports", {}).get("video_receive_dk"),
}

def check_port(port):
    """
    Run tcpdump on the given UDP port.
    Returns True if a packet is captured within 1 second, otherwise False.
    """
    cmd = ["sudo", "tcpdump", "-n", "-i", "any", "udp", "port", str(port), "-c", "1"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1)
        # If tcpdump returns exit code 0 and produces output, assume the port is live.
        if result.returncode == 0 and result.stdout:
            return True
        else:
            return False
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        logging.error(f"Error checking port {port}: {e}")
        return False

def main():
    while True:
        # Check each endpoint.
        audio_status = {label: (check_port(port) if port else False)
                        for label, port in endpoints_audio.items()}
        video_status = {label: (check_port(port) if port else False)
                        for label, port in endpoints_video.items()}
        
        # Build status strings.
        output = "Audio:\n"
        for label in endpoints_audio:
            output += f"{label}: {'Yes!' if audio_status[label] else 'No!'}\n"
        output += "\nVideo:\n"
        for label in endpoints_video:
            output += f"{label}: {'Yes!' if video_status[label] else 'No!'}\n"
        
        # Clear the console and print the updated status.
        print("\033[H\033[J" + output, end="", flush=True)
        
        time.sleep(1)

if __name__ == "__main__":
    main()
