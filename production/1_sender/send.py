#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import os
import sys
import signal
import threading
import argparse
import time

# Initialize GStreamer
Gst.init(None)

# Ensure parent directory is in sys.path to import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

#########################################
# AudioSender Class
#########################################
class AudioSender:
    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.pipeline = None
        self.loop = None
        self.clock = None

        # These will be set from config:
        self.server_ip = None
        self.audio_send_port = None
        self.audio_recv_port = None

    def set_clock(self, clock):
        self.clock = clock

    def print_clock_time(pipeline):
        clock = pipeline.get_clock()
        if clock:
            current_time = clock.get_time()
            print("Current pipeline clock time:", current_time)
        else:
            print("Pipeline clock is None!")
        return True  # Returning True keeps the timeout active

    def build_pipeline(self):
        config = load_config()

        # Server or remote IP for SRT:
        self.server_ip = config.get("server_ip", "127.0.0.1")
        if not self.server_ip:
            print("ERROR: 'server_ip' not defined in config.")
            sys.exit(1)

        # Choose ports based on country.
        if self.country.lower() == "tn":
            self.audio_send_port = config.get("ports", {}).get("audio_send_tn")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_tn")
        else:
            self.audio_send_port = config.get("ports", {}).get("audio_send_dk")
            self.audio_recv_port = config.get("ports", {}).get("audio_receive_dk")

        if not self.audio_send_port or not self.audio_recv_port:
            print("ERROR: Missing audio ports in config (send/receive).")
            sys.exit(1)

        # Basic audio parameters.
        audio_format = config.get("audio", {}).get("format", "S16LE")
        audio_rate = config.get("audio", {}).get("rate", 48000)
        channels = config.get("audio", {}).get("channels", 2)
        encoding_name = config.get("audio", {}).get("encoding_name", "L16")

        # SRT streaming settings (for sending)
        streaming_settings = config.get("streaming_settings_audio", "")

        # webrtcdsp settings:
        dsp_cfg = config.get("webrtcdsp_settings", {})
        echo_cancel = dsp_cfg.get("echo-cancel", True)
        # (Other DSP options can be added if needed)

        # Build the pipeline. (Modify as needed.)
        pipeline_str = f"""
            srtsrc uri="srt://{self.server_ip}:{self.audio_recv_port}?mode=caller" wait-for-connection=false 
                ! queue max-size-time=2000000000 max-size-buffers=500
                ! application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={channels}
                ! rtpL16depay
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcechoprobe
                ! queue
                ! alsasink device={self.device} async=false

            alsasrc device={self.device}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format=S16LE,channels={channels},rate={audio_rate}
                ! webrtcdsp echo-cancel={str(echo_cancel).lower()}
                ! queue
                ! audioconvert
                ! audioresample
                ! audio/x-raw,format={audio_format},channels={channels},rate={audio_rate}
                ! rtpL16pay
                ! srtsink uri="srt://{self.server_ip}:{self.audio_send_port}?mode=caller&{streaming_settings}"
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("AudioSender: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"AudioSender: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("AudioSender (Send+Receive) Pipeline:\n" + pipeline_str + "\n", flush=True)

        self.pipeline = Gst.parse_launch(pipeline_str)

        # Use the shared clock if provided.
        if self.clock:
            self.pipeline.use_clock(self.clock)
            self.pipeline.set_locked_state(True)  # Force the pipeline to use the provided clock.
        else:
            system_clock = Gst.SystemClock.obtain()
            self.pipeline.use_clock(system_clock)
            self.pipeline.set_locked_state(True)

        print("AudioSender using clock:", self.pipeline.get_clock())

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.pipeline.set_locked_state(True)  # Ensure the pipeline uses our provided clock

        # Print the clock every 5 seconds:
        GLib.timeout_add_seconds(5, print_clock_time, self.pipeline)
        self.loop = GLib.MainLoop()
        
        try:
            self.loop.run()
        except Exception as e:
            print(f"AudioSender: Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("AudioSender: Pipeline stopped.")


#########################################
# VideoSender Class
#########################################
class VideoSender:
    def __init__(self, device, country):
        self.device = device  # Not used for video, included for consistency.
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

        # Choose video send port based on country.
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
        print("VideoSender Pipeline:\n" + pipeline_str + "\n", flush=True)
        self.pipeline = Gst.parse_launch(pipeline_str)

        # Use the shared clock if provided.
        if self.clock:
            self.pipeline.use_clock(self.clock)
        else:
            self.pipeline.use_clock(Gst.SystemClock.obtain())

        # (Optional: print the clock to verify)
        print("VideoSender using clock:", self.pipeline.get_clock())

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

#########################################
# SenderManager: Runs both Audio and Video senders
#########################################
class SenderManager:
    def __init__(self, device, country):
        self.device = device
        self.country = country
        self.shutdown_event = threading.Event()
        # Create a shared clock for all pipelines.
        self.shared_clock = Gst.SystemClock.obtain()
        self.audio_sender = None
        self.video_sender = None

    def run_audio_worker(self):
        while not self.shutdown_event.is_set():
            print("SenderManager: Starting audio sender...")
            audio_sender = AudioSender(self.device, self.country)
            self.audio_sender = audio_sender
            audio_sender.set_clock(self.shared_clock)
            try:
                audio_sender.run()  # Blocks until the audio pipeline stops
            except Exception as e:
                print(f"SenderManager: Audio sender exception: {e}")
            self.audio_sender = None
            if self.shutdown_event.is_set():
                break
            print("SenderManager: Audio sender stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

    def run_video_worker(self):
        while not self.shutdown_event.is_set():
            print("SenderManager: Starting video sender...")
            video_sender = VideoSender(self.device, self.country)
            self.video_sender = video_sender
            video_sender.set_clock(self.shared_clock)
            try:
                video_sender.run()  # Blocks until the video pipeline stops
            except Exception as e:
                print(f"SenderManager: Video sender exception: {e}")
            self.video_sender = None
            if self.shutdown_event.is_set():
                break
            print("SenderManager: Video sender stopped unexpectedly. Restarting in 5 seconds...")
            time.sleep(5)

    def start(self):
        # Start both audio and video sender threads.
        self.audio_thread = threading.Thread(target=self.run_audio_worker)
        self.video_thread = threading.Thread(target=self.run_video_worker)
        self.audio_thread.start()
        self.video_thread.start()

    def stop(self):
        print("SenderManager: Stopping sender manager...")
        self.shutdown_event.set()
        if self.audio_sender is not None:
            self.audio_sender.stop()
        if self.video_sender is not None:
            self.video_sender.stop()
        self.audio_thread.join()
        self.video_thread.join()
        print("SenderManager: All sender workers stopped.")

#########################################
# Signal Handler and Main
#########################################
def signal_handler(sig, frame, manager):
    print("SenderManager: Interrupt received, shutting down...")
    manager.stop()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Combined Audio and Video Sender Script")
    parser.add_argument("--device", required=True, help="Audio device (e.g., hw:0,0)")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    manager = SenderManager(args.device, args.country)
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, manager))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, manager))
    manager.start()

    # Keep main thread alive.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop()

if __name__ == "__main__":
    main()
