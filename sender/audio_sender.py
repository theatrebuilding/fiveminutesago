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

def build_audio_pipeline(cfg):
    audio_cfg = cfg["audio"]
    srt_cfg   = cfg["srt"]

    # Audio parameters
    audio_src     = audio_cfg.get("src", "alsasrc")
    audio_device  = audio_cfg.get("hardware_device", "hw:3,0")
    audio_rate    = audio_cfg.get("rate", 44100)
    audio_channels= audio_cfg.get("channels", 2)
    audio_bitrate = audio_cfg.get("bitrate", 128)

    # SRT parameters
    latency     = srt_cfg.get("latency", 100)
    rbuf        = srt_cfg.get("rbuf", 32768)
    wbuf        = srt_cfg.get("wbuf", 32768)
    tsbpd_delay = srt_cfg.get("tsbpdDelay", 2000)
    srt_host    = srt_cfg.get("host", "178.249.52.14")

    srt_audio_uri = (
        f"srt://{srt_host}:7702?mode=caller&latency={latency}&"
        f"rbuf={rbuf}&wbuf={wbuf}&tsbpdDelay={tsbpd_delay}"
    )

    pipeline_str = f"""
        {audio_src} !
          device={audio_device} !
          audioconvert !
          audioresample !
          lamemp3enc target=1 bitrate=192 !
          rtpmpapay ! 
          srtsink uri="{srt_audio_uri}"
    """

    return pipeline_str

def main():
    cfg = load_config()
    pipeline_str = build_audio_pipeline(cfg)
    print("Audio GStreamer pipeline:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print("GStreamer AUDIO ERROR:", err, dbg)
        elif msg.type == Gst.MessageType.EOS:
            print("Audio End of Stream reached.")
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
        print("Audio pipeline stopped.")

if __name__ == "__main__":
    main()
