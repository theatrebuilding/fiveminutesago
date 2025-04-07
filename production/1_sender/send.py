#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import argparse
import threading
import signal
import sys
import time

from audio_send import AudioSender
from video_send import VideoSender

Gst.init(None)

class SenderManager:
    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.shutdown_event = threading.Event()
        # Create a shared clock for both sender pipelines.
        self.shared_clock = Gst.SystemClock.obtain()
        # Hold references to active sender instances.
        self.audio_sender = None
        self.video_sender = None

    def run_audio_worker(self):
        while not self.shutdown_event.is_set():
            print("SenderManager: Starting audio sender...")
            audio_sender = AudioSender(self.device, self.country)
            self.audio_sender = audio_sender  # Store reference.
            audio_sender.set_clock(self.shared_clock)
            try:
                audio_sender.run()  # Blocks until pipeline stops
            except Exception as e:
                print(f"SenderManager: Audio sender encountered an exception: {e}")
            self.audio_sender = None
            if self.shutdown_event.is_set():
                break
            print("SenderManager: Audio sender stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

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
        self.audio_thread = threading.Thread(target=self.run_audio_worker)
        self.video_thread = threading.Thread(target=self.run_video_worker)
        self.audio_thread.start()
        self.video_thread.start()

    def stop(self):
        print("SenderManager: Stopping sender manager...")
        self.shutdown_event.set()
        # Signal the active sender instances to stop their main loops.
        if self.audio_sender is not None:
            self.audio_sender.stop()
        if self.video_sender is not None:
            self.video_sender.stop()
        self.audio_thread.join()
        self.video_thread.join()
        print("SenderManager: All sender workers stopped.")

def signal_handler(sig, frame, manager):
    print("SenderManager: Interrupt received, shutting down...")
    manager.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Robust Sender Script (Video + Audio)")
    parser.add_argument("--device", required=True, help="Audio device to use (e.g., hw:0,0)")
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
