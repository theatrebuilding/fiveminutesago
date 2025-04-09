#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import os
import sys
import signal
import argparse
import time
import subprocess

# Initialize GStreamer.
Gst.init(None)

# Ensure the parent directory is in sys.path to import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

#########################################
# VideoSender Class (unchanged)
#########################################
class VideoSender:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_ip = None
        self.video_send_port = None
        self.clock = None

    def set_clock(self, clock):
        self.clock = clock

    def build_pipeline(self):
        cfg = load_config()
        self.server_ip = cfg.get("server_ip", "127.0.0.1")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        # Choose the video send port based on the country.
        if self.country.lower() == "tn":
            self.video_send_port = cfg.get("ports", {}).get("video_send_tn")
        else:
            self.video_send_port = cfg.get("ports", {}).get("video_send_dk")

        if not self.video_send_port:
            print("ERROR: video send port not defined in config.")
            sys.exit(1)

        streaming_settings = cfg.get("streaming_settings_video", "")
        video_opts = cfg.get("video", {})
        video_source = video_opts.get("source", "/dev/video0")
        bitrate = video_opts.get("bitrate", 1000)
        key_int_max = video_opts.get("key_int_max", 15)
        tune = video_opts.get("tune", "zerolatency")
        video_encoder = video_opts.get("encoder", "x264enc")
        alignment = video_opts.get("alignment", "nal")
        bframes = video_opts.get("bframes", 0)
        aud_bool = video_opts.get("aud", True)
        byte_stream = video_opts.get("byte_stream", True)
        config_interval = video_opts.get("config_interval", 1)
        video_width = video_opts.get("width", 1920)
        video_height = video_opts.get("height", 1080)

        aud_str = "true" if aud_bool else "false"
        byte_stream_str = "true" if byte_stream else "false"

        # The pipeline string contains the video source and a branch for fallback video.
        pipeline_str = f"""
            {video_source} !
            videoconvert ! videoscale ! video/x-raw,width={video_width},height={video_height} !
            {video_encoder} bitrate={bitrate} tune={tune} key-int-max={key_int_max} bframes={bframes} aud={aud_str} byte-stream={byte_stream_str} !
            video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline !
            h264parse config-interval={config_interval} !
            queue !
            mpegtsmux alignment={alignment} !
            srtsink uri="srt://{self.server_ip}:{self.video_send_port}?mode=caller&{streaming_settings}"
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            print("[VideoSender] End of Stream")
            self.stop()
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[VideoSender] ERROR -> {err}")
            if debug:
                print(f"[VideoSender] Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("[VideoSender] Pipeline:\n" + pipeline_str + "\n", flush=True)
        self.pipeline = Gst.parse_launch(pipeline_str)

        # Set the clock (either the provided one or a new system clock).
        if self.clock:
            self.pipeline.use_clock(self.clock)
            self.pipeline.set_locked_state(True)
        else:
            self.pipeline.use_clock(Gst.SystemClock.obtain())
            self.pipeline.set_locked_state(True)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        print("[VideoSender] Setting state to PLAYING...")
        self.pipeline.set_state(Gst.State.PLAYING)

        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"[VideoSender] Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("[VideoSender] Pipeline stopped.")

    def stop(self):
        if self.loop:
            self.loop.quit()

#########################################
# Main Function with Option for Audio
#########################################
def main():
    parser = argparse.ArgumentParser(description="Video Sender Script with Optional Audio Subprocess")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    # Prompt the user whether to run audio in a subprocess.
    run_audio_input = input("Do you want to run the audio subprocess? (y/n): ").strip().lower()
    run_audio = run_audio_input.startswith('y')

    audio_proc = None
    if run_audio:
        # Ask the user to specify the audio device.
        device = input("Enter the audio device name (or leave blank for default): ").strip()
        # Build the command to pass the audio device.
        audio_cmd = ["python3", "send_audio.py", "--country", args.country]
        if device:
            audio_cmd.extend(["--device", device])
        print("Launching audio sender subprocess:", " ".join(audio_cmd))
        audio_proc = subprocess.Popen(audio_cmd)

    video_sender = VideoSender(args.country)
    shared_clock = Gst.SystemClock.obtain()
    video_sender.set_clock(shared_clock)

    # Signal handler to gracefully shutdown both video and audio.
    def handle_signal(sig, frame):
        print("[Main] Interrupt received, shutting down...")
        video_sender.stop()
        if audio_proc:
            print("[Main] Terminating audio process...")
            audio_proc.terminate()
            try:
                # Wait up to 5 seconds for the audio process to exit.
                audio_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[Main] Audio process did not terminate in time; force killing it.")
                audio_proc.kill()
        sys.exit(0)


    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Run the video sender in a loop (with fallback if it stops unexpectedly).
    while True:
        try:
            video_sender.run()
        except Exception as e:
            print(f"[Main] Video sender exception: {e}")
        print("[Main] Video sender stopped unexpectedly. Restarting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    main()
