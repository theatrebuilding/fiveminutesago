import gi
import sys
import socketio
import threading
import yaml

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

# Load settings from config.yaml
CONFIG_FILE = "config.yaml"

def load_config():
    with open(CONFIG_FILE, "r") as file:
        return yaml.safe_load(file)

# ----- SOCKET.IO CLIENT FOR DASHBOARD COMMUNICATION -----
sio = socketio.Client()

DASHBOARD_URL = "http://127.0.0.1:7799"

try:
    sio.connect(DASHBOARD_URL)
    print(f"✅ Connected to dashboard at {DASHBOARD_URL}")
except Exception as e:
    print(f"⚠️ Could not connect to dashboard: {e}")

# Define default connection status
connection_status = {
    "A": False,
    "C": False,
    "B": False,
    "D": False
}

# Function to update dashboard
def update_status(node, is_connected):
    global connection_status
    if connection_status[node] != is_connected:
        print(f"🔄 Updating status: {node} -> {'Connected' if is_connected else 'Disconnected'}")
    connection_status[node] = is_connected
    sio.emit("update_status", connection_status)

# ----- BUILD GStreamer PIPELINE -----
def build_pipeline(config):
    node_B_out = config["srt"]["output"]["node_B"]["uri"]
    node_D_out = config["srt"]["output"]["node_D"]["uri"]

    video_A_fallback = config["fallback"]["video_A"]
    audio_A_fallback = config["fallback"]["audio_A"]
    video_C_fallback = config["fallback"]["video_C"]
    audio_C_fallback = config["fallback"]["audio_C"]

    bitrate = config["encoding"]["video"]["bitrate"]
    key_int_max = config["encoding"]["video"]["key_int_max"]

    # Test source only pipeline
    pipeline_str = f"""
    input-selector name=video_selector_A
    input-selector name=audio_selector_A
    input-selector name=video_selector_C
    input-selector name=audio_selector_C

    # Test sources as primary input
    videotestsrc pattern={video_A_fallback} is-live=true ! videoconvert ! video/x-raw,format=I420 ! video_selector_A.sink_0
    audiotestsrc wave={audio_A_fallback} is-live=true ! audioconvert ! audio_selector_A.sink_0

    videotestsrc pattern={video_C_fallback} is-live=true ! videoconvert ! video/x-raw,format=I420 ! video_selector_C.sink_0
    audiotestsrc wave={audio_C_fallback} is-live=true ! audioconvert ! audio_selector_C.sink_0

    # Encoding and SRT Output
    video_selector_A. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerA
    audio_selector_A. ! opusenc ! muxerA.
    muxerA. ! queue ! srtsink uri={node_B_out}

    video_selector_C. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerC
    audio_selector_C. ! opusenc ! muxerC.
    muxerC. ! queue ! srtsink uri={node_D_out}
    """

    return pipeline_str

def main():
    config = load_config()
    pipeline_str = build_pipeline(config)

    print("🚀 Starting GStreamer pipeline with config:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    # ----- MESSAGE HANDLER -----
    def on_message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            print(f"❌ GStreamer ERROR: {err} {debug}")
        elif msg.type == Gst.MessageType.EOS:
            print("✅ End of Stream reached.")
        elif msg.type == Gst.MessageType.STATE_CHANGED:
            if msg.src == pipeline:
                old_state, new_state, pending = msg.parse_state_changed()
                print(f"🔄 Pipeline state changed: {old_state.value_nick} -> {new_state.value_nick}")

    bus.connect("message", on_message)

    # Start pipeline
    pipeline.set_state(Gst.State.PLAYING)
    state_return = pipeline.get_state(5 * Gst.SECOND)
    
    print(f"🧐 Pipeline final state: {state_return.state}")
    
    if state_return.state != Gst.State.PLAYING:
        print("❌ ERROR: Pipeline failed to start!")
    else:
        print("✅ Pipeline started successfully!")

    # Keep the pipeline running
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("🛑 Shutting down GStreamer pipeline...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
