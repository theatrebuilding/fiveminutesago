#!/usr/bin/env python3

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import os
import sys
import signal

# Insert parent directory to access config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

class VideoSender:
    def __init__(self, device, country):
        self.device = device  # Not used for video, but included for consistency.
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
        self.server_ip = cfg.get("server_ip")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        # Choose the video send port based on the country.
        if self.country.lower() == "tn":
            self.video_send_port = cfg.get("ports", {}).get("video_send_tn")
        else:
            self.video_send_port = cfg.get("ports", {}).get("video_send_dk")

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
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("VideoSender: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"VideoSender: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("VideoSender: Pipeline:\n" + pipeline_str + "\n", flush=True)
        self.pipeline = Gst.parse_launch(pipeline_str)

        # Use the shared clock if provided.
        if self.clock:
            self.pipeline.use_clock(self.clock)
        else:
            system_clock = Gst.SystemClock.obtain()
            self.pipeline.use_clock(system_clock)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"VideoSender: Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("VideoSender: Pipeline stopped.")


    def stop(self):
        if self.loop:
            self.loop.quit()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Video Sender Script")
    parser.add_argument("--device", required=True, help="Device parameter (for consistency)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()
    sender = VideoSender(args.device, args.country)
    sender.run()
