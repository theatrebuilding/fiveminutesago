#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import signal
import sys
import argparse
import threading
import time

# Import the pipeline builders
from audio_receive import AudioReceiver
from video_receive import VideoReceiver

Gst.init(None)

class ReceiverManager:
    def __init__(self, country, audio_device):
        self.country = country
        self.audio_device = audio_device
        # Create a shared system clock
        self.shared_clock = Gst.SystemClock.obtain()
        self.shutdown_event = threading.Event()
        # Hold references to active receiver instances.
        self.audio_receiver = None
        self.video_receiver = None

    def run_audio_worker(self):
        while not self.shutdown_event.is_set():
            print("ReceiverManager: Starting audio receiver...")
            audio_receiver = AudioReceiver(self.country, self.audio_device)
            self.audio_receiver = audio_receiver  # Store reference.
            audio_receiver.set_clock(self.shared_clock)
            try:
                # This call blocks until the pipeline stops (EOS or error)
                audio_receiver.run()
            except Exception as e:
                print(f"ReceiverManager: Audio receiver encountered an exception: {e}")
            self.audio_receiver = None
            if self.shutdown_event.is_set():
                break
            print("ReceiverManager: Audio receiver stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

    def run_video_worker(self):
        while not self.shutdown_event.is_set():
            print("ReceiverManager: Starting video receiver...")
            video_receiver = VideoReceiver(self.country)
            self.video_receiver = video_receiver  # Store reference.
            video_receiver.set_clock(self.shared_clock)
            try:
                video_receiver.run()
            except Exception as e:
                print(f"ReceiverManager: Video receiver encountered an exception: {e}")
            self.video_receiver = None
            if self.shutdown_event.is_set():
                break
            print("ReceiverManager: Video receiver stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

    def start(self):
        self.audio_thread = threading.Thread(target=self.run_audio_worker)
        self.video_thread = threading.Thread(target=self.run_video_worker)
        self.audio_thread.start()
        self.video_thread.start()

    def stop(self):
        print("ReceiverManager: Stopping receiver manager...")
        self.shutdown_event.set()
        # If an audio or video receiver is active, signal it to quit its main loop.
        if self.audio_receiver is not None:
            self.audio_receiver.stop()
        if self.video_receiver is not None:
            self.video_receiver.stop()
        self.audio_thread.join()
        self.video_thread.join()
        print("ReceiverManager: All receiver workers stopped.")

def signal_handler(sig, frame, manager):
    print("ReceiverManager: Interrupt received, shutting down...")
    manager.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Robust Receiver Manager Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    parser.add_argument("--device", required=True, help="Audio output device (e.g., hw:0,0)")
    args = parser.parse_args()

    manager = ReceiverManager(args.country, args.device)
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, manager))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, manager))
    manager.start()

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()

if __name__ == "__main__":
    main()
