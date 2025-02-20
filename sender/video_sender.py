#!/usr/bin/env python3
import gi
import yaml
import os
import sys

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

CONFIG_FILE = "config.yaml"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: Config file '{CONFIG_FILE}' not found.")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

def build_video_pipeline(cfg):
    video_cfg = cfg["video"]
    srt_cfg = cfg["srt"]

    # Video parameters
    video_src    = video_cfg.get("video_src", "v4l2src")
    tune         = video_cfg.get("tune", "zerolatency")
    bitrate      = video_cfg.get("bitrate", 1000)
    key_int_max  = video_cfg.get("key_int_max", 15)
    bframes      = video_cfg.get("bframes", 0)
    aud_bool     = video_cfg.get("aud", True)
    option_str   = video_cfg.get("option_string", "repeat-headers=1")
    byte_stream  = video_cfg.get("byte_stream", True)
    config_interval = video_cfg.get("config_interval", 1)
    alignment    = video_cfg.get("alignment", 7)

    aud_str = "true" if aud_bool else "false"
    byte_stream_str = "true" if byte_stream else "false"

    # SRT parameters
    latency     = srt_cfg.get("latency", 100)
    rbuf        = srt_cfg.get("rbuf", 32768)
    wbuf        = srt_cfg.get("wbuf", 32768)
    tsbpd_delay = srt_cfg.get("tsbpdDelay", 2000)
    srt_host    = srt_cfg.get("host", "178.249.52.14")

    srt_video_uri = (
        f"srt://{srt_host}:7701?mode=caller&latency={latency}&"
        f"rbuf={rbuf}&wbuf={wbuf}&tsbpdDelay={tsbpd_delay}"
    )

    pipeline_str = f"""
        {video_src} !
          videoconvert !
          x264enc tune={tune} bitrate={bitrate} key-int-max={key_int_max} bframes={bframes} aud={aud_str} byte-stream={byte_stream_str} option-string="{option_str}" !
          video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline !
          h264parse config-interval={config_interval} !
          queue !
          mpegtsmux name=mux alignment={alignment} !
          srtsink uri="{srt_video_uri}"
    """
    return pipeline_str

def main():
    cfg = load_config()
    pipeline_str = build_video_pipeline(cfg)
    print("Video GStreamer pipeline:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print("GStreamer VIDEO ERROR:", err, dbg)
        elif msg.type == Gst.MessageType.EOS:
            print("Video End of Stream reached.")
        return True

    bus.connect("message", on_message)
    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()

    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Video pipeline stopped.")

if __name__ == "__main__":
    main()
