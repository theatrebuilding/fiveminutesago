#!/usr/bin/env python3
import subprocess
import sys
import signal
import threading

# Function to read and print output from subprocess streams!
def stream_reader(prefix, stream):
    try:
        for line in iter(stream.readline, ''):
            if line:
                print(f"{prefix}: {line}", end='')
    except Exception as e:
        print(f"{prefix} reader error: {e}")
    finally:
        stream.close()

def main():
    try:
        # Start video subprocess in unbuffered mode
        video_proc = subprocess.Popen(
            [sys.executable, "-u", "video_send.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        # Start audio subprocess in unbuffered mode
        audio_proc = subprocess.Popen(
            [sys.executable, "-u", "audio_send.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    except Exception as e:
        print(f"Failed to start subprocesses: {e}")
        sys.exit(1)

    # Create threads to read outputs from subprocesses
    threads = [
        threading.Thread(target=stream_reader, args=("VIDEO", video_proc.stdout)),
        threading.Thread(target=stream_reader, args=("AUDIO", audio_proc.stdout)),
        threading.Thread(target=stream_reader, args=("VIDEO ERROR", video_proc.stderr)),
        threading.Thread(target=stream_reader, args=("AUDIO ERROR", audio_proc.stderr))
    ]

    # Start threads
    for t in threads:
        t.start()

    # Define a signal handler for graceful termination of subprocesses
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

    # Register signal handler for SIGINT and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for subprocesses to complete
    video_return_code = video_proc.wait()
    audio_return_code = audio_proc.wait()

    # Check subprocess return codes and print if abnormal termination occurs
    if video_return_code != 0:
        print(f"Video subprocess exited with code {video_return_code}")

    if audio_return_code != 0:
        print(f"Audio subprocess exited with code {audio_return_code}")

    # Wait for all threads to finish reading subprocess outputs
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
