import gi
import yaml
import os
import sys
import signal

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

def on_message(bus, message):
    t = message.type
    if t == Gst.MessageType.EOS:
        print("End of stream")
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Error: {err}, Debug info: {debug}")

def build_pipeline(cfg):
    srt_cfg = cfg["srt"]
    
    srt_video_src = srt_cfg.get("video_src", "srt://:7701?mode=listener")
    srt_video_sink = srt_cfg.get("video_sink", "srt://:7702?mode=listener")
    srt_audio_src = srt_cfg.get("audio_src", "srt://:8801?mode=listener")
    srt_audio_sink = srt_cfg.get("audio_sink", "srt://:8802?mode=listener")
    
    pipeline_str = f"""
    srtsrc uri="{srt_video_src}" ! queue ! srtsink uri="{srt_video_sink}"
    srtsrc uri="{srt_audio_src}" ! queue ! srtsink uri="{srt_audio_sink}"
    """
    
    return pipeline_str

def signal_handler(sig, frame):
    print("Interrupt received, stopping pipeline...")
    loop.quit()

def main():
    global loop
    cfg = load_config()
    pipeline_str = build_pipeline(cfg)
    print("GStreamer pipeline:\n", pipeline_str, "\n")
    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)
    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")

if __name__ == "__main__":
    main()
