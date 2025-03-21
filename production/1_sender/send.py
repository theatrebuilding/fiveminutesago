#!/usr/bin/env python3
# Run with:
#   python3 send.py --device hw:0,0 --country tn
#   python3 send.py --device hw:0,0 --country dk

import os
import subprocess
import sys
import signal
import threading
import argparse
import time

def stream_reader(prefix, stream):
    """Reads lines from a stream and prints them with a prefix."""
    try:
        for line in iter(stream.readline, ''):
            if line:
                print(f"{prefix}: {line}", end='')
    except Exception as e:
        print(f"{prefix} reader error: {e}")
    finally:
        stream.close()

def main():
    parser = argparse.ArgumentParser(description="Sender Script (Video Only)")
    parser.add_argument("--device", required=True, help="Audio device to use (not used here, but retained for consistency)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    device = args.device
    country = args.country

    # Copy the current environment so child processes inherit it
    env = os.environ.copy()

    try:
        # Start ONLY the video subprocess
        video_proc = subprocess.Popen(
            [sys.executable, "-u", "video_send.py", "--device", device, "--country", country],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )
    except Exception as e:
        print(f"Failed to start video subprocess: {e}")
        sys.exit(1)

    # Create threads to read output from the subprocess
    threads = [
        threading.Thread(target=stream_reader, args=("VIDEO", video_proc.stdout)),
        threading.Thread(target=stream_reader, args=("VIDEO ERROR", video_proc.stderr))
    ]
    for t in threads:
        t.start()

    def signal_handler(sig, frame):
        print("\nTerminating video subprocess...")
        video_proc.terminate()
        try:
            video_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            video_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for the video subprocess to complete
    video_return_code = video_proc.wait()

    if video_return_code != 0:
        print(f"Video subprocess exited with code {video_return_code}")

    # Join the reader threads
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
