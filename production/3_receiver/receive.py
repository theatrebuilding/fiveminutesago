#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal
import sys
import argparse
import threading

# Import the pipeline builders
from audio_receive import AudioReceiver
from video_receive import VideoReceiver

Gst.init(None)

class Receiver:
    def __init__(self, country, audio_device):
        self.country = country
        self.audio_device = audio_device
        self.audio_receiver = None
        self.video_receiver = None

    def start(self):
        # Create a shared system clock
        shared_clock = Gst.SystemClock.obtain()
        
        # Start audio receiver in a separate thread
        self.audio_receiver = AudioReceiver(self.country, self.audio_device)
        self.audio_receiver.set_clock(shared_clock)
        audio_thread = threading.Thread(target=self.audio_receiver.run)
        audio_thread.start()

        # Start video receiver in a separate thread
        self.video_receiver = VideoReceiver(self.country)
        self.video_receiver.set_clock(shared_clock)
        video_thread = threading.Thread(target=self.video_receiver.run)
        video_thread.start()

        # Wait for both threads to finish
        audio_thread.join()
        video_thread.join()

    def stop(self):
        if self.audio_receiver:
            self.audio_receiver.stop()
        if self.video_receiver:
            self.video_receiver.stop()

def signal_handler(sig, frame, receiver):
    print("Receiver: Interrupt received, stopping pipelines...")
    receiver.stop()
    sys.exit(0)

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Receiver Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    parser.add_argument("--device", required=True, help="Audio output device (e.g., hw:0,0)")
    args = parser.parse_args()

    receiver = Receiver(args.country, args.device)

    # Handle termination signals
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))

    receiver.start()

if __name__ == "__main__":
    main()
