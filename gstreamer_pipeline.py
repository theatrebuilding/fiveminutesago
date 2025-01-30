import gi
import yaml
import sys
import socketio
import os
import threading
import psutil

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

# Load settings from config.yaml
CONFIG_FILE = "config.yaml"

def load_config():
    try:
        with open(CONFIG_FILE, "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"❌ ERROR: Config file {CONFIG_FILE} not found!")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ ERROR: Failed to parse {CONFIG_FILE}: {e}")
        sys.exit(1)

# ----- SOCKET.IO CLIENT FOR DASHBOARD COMMUNICATION -----
sio = socketio.Client()
DASHBOARD_URL = "http://127.0.0.1:7799"

def connect_dashboard():
    try:
        sio.connect(DASHBOARD_URL)
        print(f"✅ Connected to dashboard at {DASHBOARD_URL}")
    except Exception as e:
        print(f"⚠️ Could not connect to dashboard: {e}")
        sys.exit(1)

connection_status = {"A": False, "C": False, "B": False, "D": False}

def update_status(node, is_connected: bool):
    if connection_status[node] != is_connected:
        print(f"🔄 Updating status: {node} -> {'Connected' if is_connected else 'Disconnected'}")
    connection_status[node] = is_connected
    sio.emit("update_status", connection_status)
    print(f"📤 Sent status update: {connection_status}")

# ----- BUILD GStreamer PIPELINE -----
def build_pipeline(config):
    try:
        node_A_in = config["srt"]["input"]["node_A"]["uri"]
        node_C_in = config["srt"]["input"]["node_C"]["uri"]
        node_B_out = config["srt"]["output"]["node_B"]["uri"]
        node_D_out = config["srt"]["output"]["node_D"]["uri"]
        
        video_A_fallback = config["fallback"]["video_A"]
        audio_A_fallback = config["fallback"]["audio_A"]
        video_C_fallback = config["fallback"]["video_C"]
        audio_C_fallback = config["fallback"]["audio_C"]

        bitrate = config["encoding"]["video"]["bitrate"]
        key_int_max = config["encoding"]["video"]["key_int_max"]
    except KeyError as e:
        print(f"❌ ERROR: Missing required configuration value: {e}")
        sys.exit(1)

    return f"""
    input-selector name=video_selector_A
    input-selector name=audio_selector_A
    input-selector name=video_selector_C
    input-selector name=audio_selector_C

    srtsrc uri={node_A_in} ! tsdemux name=demuxA
      demuxA. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_A.sink_0
      demuxA. ! queue ! opusdec ! audioconvert ! audio_selector_A.sink_0

    srtsrc uri={node_C_in} ! tsdemux name=demuxC
      demuxC. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_C.sink_0
      demuxC. ! queue ! opusdec ! audioconvert ! audio_selector_C.sink_0

    videotestsrc pattern={video_A_fallback} ! videoconvert ! video_selector_A.sink_1
    audiotestsrc wave={audio_A_fallback} ! audioconvert ! audio_selector_A.sink_1

    videotestsrc pattern={video_C_fallback} ! videoconvert ! video_selector_C.sink_1
    audiotestsrc wave={audio_C_fallback} ! audioconvert ! audio_selector_C.sink_1

    video_selector_A. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerA
    audio_selector_A. ! opusenc ! muxerA.
    muxerA. ! queue ! srtsink uri={node_B_out}

    video_selector_C. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerC
    audio_selector_C. ! opusenc ! muxerC.
    muxerC. ! queue ! srtsink uri={node_D_out}
    """

def main():
    config = load_config()
    connect_dashboard()
    pipeline_str = build_pipeline(config)
    print("🚀 Starting GStreamer pipeline...")

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_message(bus, msg):
        print(f"📩 GStreamer Message: {msg.type}")
        return True

    bus.connect("message", on_message)
    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("🛑 Shutting down GStreamer pipeline...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
