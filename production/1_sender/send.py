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
    parser = argparse.ArgumentParser(description="Sender Script (Video + Audio)")
    parser.add_argument("--device", required=True, help="Audio device to use (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    device = args.device
    country = args.country

    # Copy the current environment so child processes inherit it
    env = os.environ.copy()

    try:
        # Start the video subprocess
        video_proc = subprocess.Popen(
            [sys.executable, "-u", "video_send.py", "--device", device, "--country", country],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )

        # (Optional) Add a small delay to let video init before starting audio
        # time.sleep(1)

        # Start the audio subprocess
        audio_proc = subprocess.Popen(
            [sys.executable, "-u", "audio_send.py", "--device", device, "--country", country],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )

    except Exception as e:
        print(f"Failed to start subprocesses: {e}")
        sys.exit(1)

    # Create threads to read output from video and audio subprocesses
    threads = [
        threading.Thread(target=stream_reader, args=("VIDEO", video_proc.stdout)),
        threading.Thread(target=stream_reader, args=("VIDEO ERROR", video_proc.stderr)),
        threading.Thread(target=stream_reader, args=("AUDIO", audio_proc.stdout)),
        threading.Thread(target=stream_reader, args=("AUDIO ERROR", audio_proc.stderr))
    ]

    for t in threads:
        t.start()

    def signal_handler(sig, frame):
        print("\nTerminating subprocesses...")
        video_proc.terminate()
        audio_proc.terminate()
        try:
            video_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            video_proc.kill()
        try:
            audio_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            audio_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for both subprocesses to complete
    video_return_code = video_proc.wait()
    audio_return_code = audio_proc.wait()

    # If needed, print the exit codes
    if video_return_code != 0:
        print(f"Video subprocess exited with code {video_return_code}")
    if audio_return_code != 0:
        print(f"Audio subprocess exited with code {audio_return_code}")

    # Join the reader threads
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
