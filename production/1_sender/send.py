#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import argparse
import threading
import signal
import sys

from audio_send import AudioSender
from video_send import VideoSender

Gst.init(None)

class Sender:
    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.audio_sender = None
        self.video_sender = None

    def start(self):
        # Start audio sender in a separate thread.
        self.audio_sender = AudioSender(self.device, self.country)
        audio_thread = threading.Thread(target=self.audio_sender.run)
        audio_thread.start()

        # Start video sender in a separate thread.
        self.video_sender = VideoSender(self.device, self.country)
        video_thread = threading.Thread(target=self.video_sender.run)
        video_thread.start()

        # Wait for both threads to complete.
        audio_thread.join()
        video_thread.join()

    def stop(self):
        if self.audio_sender:
            self.audio_sender.stop()
        if self.video_sender:
            self.video_sender.stop()

def signal_handler(sig, frame, sender):
    print("\nTerminating sender pipelines...")
    sender.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Sender Script (Video + Audio)")
    parser.add_argument("--device", required=True, help="Audio device to use (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    sender = Sender(args.device, args.country)

    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, sender))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, sender))

    sender.start()

if __name__ == "__main__":
    main()
