#!/usr/bin/env python3
import subprocess
import sys
import signal
import threading

def stream_reader(prefix, stream):
    """Read lines from the given stream and print them with a prefix."""
    for line in iter(stream.readline, ''):
        if line:
            print(f"{prefix}: {line}", end='')
    stream.close()

def main():
    # Launch video_sender.py and audio_sender.py as subprocesses with piped stdout/stderr
    video_proc = subprocess.Popen(
        [sys.executable, "video_sender.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,  # ensures strings instead of bytes
        bufsize=1
    )
    audio_proc = subprocess.Popen(
        [sys.executable, "audio_sender_update1.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Create threads to read the output from each subprocess
    video_stdout_thread = threading.Thread(target=stream_reader, args=("VIDEO", video_proc.stdout))
    audio_stdout_thread = threading.Thread(target=stream_reader, args=("AUDIO", audio_proc.stdout))
    video_stderr_thread = threading.Thread(target=stream_reader, args=("VIDEO ERROR", video_proc.stderr))
    audio_stderr_thread = threading.Thread(target=stream_reader, args=("AUDIO ERROR", audio_proc.stderr))

    # Start all threads
    video_stdout_thread.start()
    audio_stdout_thread.start()
    video_stderr_thread.start()
    audio_stderr_thread.start()

    def signal_handler(sig, frame):
        print("\nTerminating subprocesses...")
        video_proc.terminate()
        audio_proc.terminate()
        sys.exit(0)

    # Register signal handler for clean exit
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for the subprocesses to complete
    video_proc.wait()
    audio_proc.wait()
    
    # Wait for the threads to finish reading the streams
    video_stdout_thread.join()
    audio_stdout_thread.join()
    video_stderr_thread.join()
    audio_stderr_thread.join()

if __name__ == "__main__":
    main()
