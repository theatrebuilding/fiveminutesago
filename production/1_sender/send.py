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
# VideoSender Class
#########################################
class VideoSender:
    def __init__(self, country, video_device=None, video_source="config", preview_pattern=None):
        self.country = country
        self.video_device = video_device
        self.video_source = video_source
        self.preview_pattern = preview_pattern
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
        video_encoder = video_opts.get("encoder", "x264enc")
        alignment = video_opts.get("alignment", "nal")
        config_interval = video_opts.get("config_interval", 1)
        video_width = video_opts.get("width", 1920)
        video_height = video_opts.get("height", 1080)
        video_framerate = video_opts.get("framerate", 30)
        video_source, source_label = self.resolve_video_source(video_opts)
        encoder_properties = self.build_encoder_properties(video_opts, video_encoder)
        profile_caps = self.build_profile_caps(video_opts, video_encoder)

        print(f"[VideoSender] Using source: {source_label}", flush=True)

        preview_branch = ""
        stream_source = """
            video_tee. ! queue !
            {video_encoder} {encoder_properties} !
            video/x-h264,stream-format=byte-stream,alignment=au{profile_caps} !
            h264parse config-interval={config_interval} !
            queue !
            mpegtsmux alignment={alignment} !
            srtsink uri="srt://{server_ip}:{video_send_port}?mode=caller&{streaming_settings}"
        """.format(
            video_encoder=video_encoder,
            encoder_properties=encoder_properties,
            profile_caps=profile_caps,
            config_interval=config_interval,
            alignment=alignment,
            server_ip=self.server_ip,
            video_send_port=self.video_send_port,
            streaming_settings=streaming_settings,
        )
        if self.preview_pattern:
            preview_location = self.preview_pattern.replace("\\", "\\\\").replace('"', '\\"')
            preview_branch = f"""
                video_tee. ! queue leaky=downstream max-size-buffers=30 max-size-bytes=0 max-size-time=0 !
                videoconvert ! videoscale ! videorate drop-only=true !
                video/x-raw,width=640,height=360,framerate=1/5 !
                jpegenc quality=70 !
                multifilesink location="{preview_location}" max-files=2 sync=false async=false
            """

        pipeline_str = f"""
            {video_source} !
            videoconvert ! videoscale ! videorate !
            video/x-raw,format=I420,width={video_width},height={video_height},framerate={video_framerate}/1,pixel-aspect-ratio=1/1,interlace-mode=progressive !
            tee name=video_tee
            {stream_source}
            {preview_branch}
        """
        return pipeline_str.strip()

    def resolve_video_source(self, video_opts):
        if self.video_device:
            return f"v4l2src device={self.video_device} do-timestamp=true", f"camera {self.video_device}"

        if (self.video_source or "config").strip().lower() == "test":
            return "videotestsrc pattern=snow is-live=true do-timestamp=true", "test signal fallback"

        config_source = video_opts.get("source", "v4l2src device=/dev/video0")
        return config_source, f"config source ({config_source})"

    def build_encoder_properties(self, video_opts, video_encoder):
        bitrate = video_opts.get("bitrate", 1000)
        key_int_max = video_opts.get("key_int_max", 15)
        tune = video_opts.get("tune", "zerolatency")
        bframes = video_opts.get("bframes", 0)
        aud_bool = video_opts.get("aud", True)
        byte_stream = video_opts.get("byte_stream", True)

        properties = [
            f"bitrate={bitrate}",
            f"key-int-max={key_int_max}",
            f"bframes={bframes}",
            f'aud={"true" if aud_bool else "false"}',
            f'byte-stream={"true" if byte_stream else "false"}',
        ]
        if tune:
            properties.append(f"tune={tune}")

        if (video_encoder or "").strip() == "x264enc":
            speed_preset = self.first_non_empty(video_opts, "speed_preset", "speed-preset")
            pass_mode = self.first_non_empty(video_opts, "pass")
            quantizer = video_opts.get("quantizer")
            option_string = self.first_non_empty(video_opts, "option_string", "option_str", "option-string")

            if speed_preset:
                properties.append(f"speed-preset={speed_preset}")
            if pass_mode:
                properties.append(f"pass={pass_mode}")
            if quantizer not in {None, ""}:
                properties.append(f"quantizer={quantizer}")
            if option_string:
                properties.append(f'option-string="{self.gst_escape(str(option_string))}"')

        return " ".join(properties)

    def build_profile_caps(self, video_opts, video_encoder):
        if (video_encoder or "").strip() != "x264enc":
            return ""
        profile = self.first_non_empty(video_opts, "profile")
        if not profile:
            return ""
        return f",profile={profile}"

    def first_non_empty(self, mapping, *keys):
        for key in keys:
            value = mapping.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
            else:
                return value
        return None

    def gst_escape(self, value):
        return value.replace("\\", "\\\\").replace('"', '\\"')

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
        if self.preview_pattern:
            os.makedirs(os.path.dirname(os.path.abspath(self.preview_pattern)), exist_ok=True)
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
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument("--with-audio", dest="with_audio", action="store_true", help="Launch the audio subprocess.")
    audio_group.add_argument("--no-audio", dest="with_audio", action="store_false", help="Do not launch the audio subprocess.")
    parser.set_defaults(with_audio=None)
    parser.add_argument("--device", help="ALSA audio device name passed to the audio subprocess.")
    parser.add_argument("--video-device", help="Video device path override, for example /host-dev/video2.")
    parser.add_argument("--video-source", choices=["config", "test"], default="config", help="Video source mode. Use 'test' to send a test signal instead of a camera.")
    parser.add_argument("--preview-pattern", help="Optional JPEG snapshot output pattern, for example /mnt/tbdrive/previews/sender-tn-preview-%05d.jpg.")
    args = parser.parse_args()

    if args.with_audio is None:
        run_audio_input = input("Do you want to run the audio subprocess? (y/n): ").strip().lower()
        run_audio = run_audio_input.startswith("y")
    else:
        run_audio = args.with_audio

    audio_proc = None
    if run_audio:
        device = args.device
        if args.with_audio is None:
            device = input("Enter the audio device name (or leave blank for default): ").strip()

        audio_cmd = ["python3", "send_audio.py", "--country", args.country]
        if device:
            audio_cmd.extend(["--device", device])
        print("Launching audio sender subprocess:", " ".join(audio_cmd))
        audio_proc = subprocess.Popen(audio_cmd)

    video_sender = VideoSender(
        args.country,
        video_device=args.video_device,
        video_source=args.video_source,
        preview_pattern=args.preview_pattern,
    )
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
