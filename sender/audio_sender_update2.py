#!/usr/bin/env python3
import subprocess
import signal
import os
import sys
import time

# SRT server IP and ports
SRT_SERVER = "178.249.52.14"
SEND_PORT = 8801
RECEIVE_PORT = 8802

# GStreamer commands for sending and receiving audio
SEND_AUDIO_CMD = f"gst-launch-1.0 -v alsasrc device=hw:3,0 ! audioconvert ! audioresample ! audio/x-raw,format=S16BE,channels=2,rate=32000 ! rtpL16pay ! srtsink uri=\"srt://{SRT_SERVER}:{SEND_PORT}?mode=caller\""

RECEIVE_AUDIO_CMD = f"gst-launch-1.0 -v srtsrc uri=\"srt://{SRT_SERVER}:{RECEIVE_PORT}?mode=caller&latency=1000&maxbw=0\" ! queue max-size-time=200000000 ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2 ! rtpL16depay ! audioconvert ! audioresample ! alsasink device=hw:2,0"

def run_command(command):
    """Runs a shell command as a subprocess and returns the process."""
    return subprocess.Popen(command, shell=True, preexec_fn=os.setsid)

def stop_processes():
    """Stops both processes when script is terminated."""
    print("\nStopping audio transmission...")
    if send_process:
        os.killpg(os.getpgid(send_process.pid), signal.SIGTERM)
    if receive_process:
        os.killpg(os.getpgid(receive_process.pid), signal.SIGTERM)
    sys.exit(0)

if __name__ == "__main__":
    print("Starting audio send & receive pipelines...")

    try:
        # Start sending and receiving audio in parallel
        send_process = run_command(SEND_AUDIO_CMD)
        receive_process = run_command(RECEIVE_AUDIO_CMD)

        # Keep script running to allow subprocesses to continue
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        stop_processes()

