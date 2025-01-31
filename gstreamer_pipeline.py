import gi
import yaml
import os
import sys

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

CONFIG_FILE = "config.yaml"

connection_status = {
    "receiveV1": False,
    "receiveA1": False,
    "sendV1": False,
    "sendA1": False
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: Config file '{CONFIG_FILE}' not found.")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

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

def on_message(bus, msg):
    global connection_status
    if msg.type == Gst.MessageType.ERROR:
        err, dbg = msg.parse_error()
        print("GStreamer ERROR:", err, dbg)
    elif msg.type == Gst.MessageType.EOS:
        print("End of Stream reached.")
    elif msg.type == Gst.MessageType.STATE_CHANGED:
        struct = msg.get_structure()
        if struct:
            name = struct.get_name()
            if "GstBaseSrc" in name:
                if "7701" in struct.to_string():
                    connection_status["receiveV1"] = True
                elif "8802" in struct.to_string():
                    connection_status["receiveA1"] = True
            if "GstBaseSink" in name:
                if "8801" in struct.to_string():
                    connection_status["sendV1"] = True
                elif "8803" in struct.to_string():
                    connection_status["sendA1"] = True
        print("Connection Status:", connection_status)
    return True

def main():
    cfg = load_config()
    pipeline_str = build_pipeline(cfg)
    print("GStreamer pipeline:\n", pipeline_str, "\n")
    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)
    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")

if __name__ == "__main__":
    main()
