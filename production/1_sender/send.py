#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import argparse
import threading
import signal
import sys
import time

from video_send import VideoSender

Gst.init(None)

class SenderManager:
    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.shutdown_event = threading.Event()
        # Create a shared clock for the sender pipeline.
        self.shared_clock = Gst.SystemClock.obtain()
        # Hold reference to active video sender instance.
        self.video_sender = None

    def run_video_worker(self):
        while not self.shutdown_event.is_set():
            print("SenderManager: Starting video sender...")
            video_sender = VideoSender(self.device, self.country)
            self.video_sender = video_sender  # Store reference.
            video_sender.set_clock(self.shared_clock)
            try:
                video_sender.run()
            except Exception as e:
                print(f"SenderManager: Video sender encountered an exception: {e}")
            self.video_sender = None
            if self.shutdown_event.is_set():
                break
            print("SenderManager: Video sender stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

    def start(self):
        self.video_thread = threading.Thread(target=self.run_video_worker)
        self.video_thread.start()

    def stop(self):
        print("SenderManager: Stopping sender manager...")
        self.shutdown_event.set()
        # Signal the active video sender instance to stop its main loop.
        if self.video_sender is not None:
            self.video_sender.stop()
        self.video_thread.join()
        print("SenderManager: Video sender worker stopped.")

def signal_handler(sig, frame, manager):
    print("SenderManager: Interrupt received, shutting down...")
    manager.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Robust Video Sender Script")
    parser.add_argument("--device", required=True, help="Device to use (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    manager = SenderManager(args.device, args.country)
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, manager))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, manager))

    manager.start()

    # Keep the main thread alive.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()

if __name__ == "__main__":
    main()
