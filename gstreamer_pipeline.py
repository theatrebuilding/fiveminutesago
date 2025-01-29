import gi
import yaml
import sys
import socketio
import os

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Ensure GStreamer is initialized
Gst.init(None)

# Load settings from config.yaml
CONFIG_FILE = "config.yaml"

def load_config():
    with open(CONFIG_FILE, "r") as file:
        return yaml.safe_load(file)

# ----- SOCKET.IO CLIENT FOR DASHBOARD COMMUNICATION -----
sio = socketio.Client()

# Try connecting to the Flask dashboard's Socket.IO server
# Adjust host/port if your dashboard is elsewhere
DASHBOARD_URL = "http://127.0.0.1:7799"

try:
    sio.connect(DASHBOARD_URL)
    print(f"Connected to dashboard at {DASHBOARD_URL}")
except Exception as e:
    print(f"Could not connect to dashboard: {e}")

# We'll track connection states in a dictionary: Node A, B, C, D
connection_status = {
    "A": False,  # Is Node A input streaming?
    "C": False,  # Is Node C input streaming?
    "B": False,  # Is Node B output receiving?
    "D": False,  # Is Node D output receiving?
}

def update_status(node, is_connected: bool):
    """Update local dictionary and emit to the Flask dashboard."""
    connection_status[node] = is_connected
    # Emit the entire dictionary so the dashboard can see all states
    print(f"Updating status: {node} -> {'Connected' if is_connected else 'Disconnected'}")  # Debug Print
    sio.emit("update_status", connection_status)

# ----- END SOCKET.IO SECTION -----

def build_pipeline(config):
    """
    Build the GStreamer pipeline string from the config dict.
    Same as your earlier code, just with a few lines referencing the dictionary.
    """

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

    pipeline_str = f"""
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

    videotestsrc pattern={video_A_fallback} ! videoconvert ! video/x-raw, format=I420 ! video_selector_A.sink_1
    audiotestsrc wave={audio_A_fallback} ! audioconvert ! audio_selector_A.sink_1

    videotestsrc pattern={video_C_fallback} ! videoconvert ! video/x-raw, format=I420 ! video_selector_C.sink_1
    audiotestsrc wave={audio_C_fallback} ! audioconvert ! audio_selector_C.sink_1

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

    print("Starting GStreamer pipeline with config:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    # We'll connect a callback to interpret messages.
    # We'll detect srtsrc or srtsink states to see if nodes are connected.
    def on_message(bus, msg):
        print(f"Received GStreamer Message: {msg.type}")  # Debug Print
        print(f"Received GStreamer Message: {msg}")
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            print("GStreamer ERROR:", err, debug)
        elif msg.type == Gst.MessageType.EOS:
            print("EOS reached. Stream ended.")
        elif msg.type == Gst.MessageType.STATE_CHANGED:
            # We can check if the message src is a srtsrc or srtsink
            src = msg.src
            if not src:
                return
            name = src.get_name()
            st_old, st_new, st_pending = msg.parse_state_changed()
            # We'll interpret node A input as srtsrc with port=7001, node C with port=7002, etc.
            # Similarly for srtsink with port=8001 => node B, port=8002 => node D

            # Check if st_new == Gst.State.PLAYING => means it's connected and playing
            # If it transitions away from PLAYING => lost connection
            if "srtsrc" in name.lower():
                if "7701" in name or "demuxa" in name.lower():
                    # Node A input
                    if st_new == Gst.State.PLAYING:
                        update_status("A", True)
                    elif st_new < Gst.State.PLAYING:
                        update_status("A", False)
                elif "7702" in name or "demuxc" in name.lower():
                    # Node C input
                    if st_new == Gst.State.PLAYING:
                        update_status("C", True)
                    elif st_new < Gst.State.PLAYING:
                        update_status("C", False)

            elif "srtsink" in name.lower():
                # Node B or D
                if "8801" in name:
                    # Node B
                    if st_new == Gst.State.PLAYING:
                        update_status("B", True)
                    elif st_new < Gst.State.PLAYING:
                        update_status("B", False)
                elif "8802" in name:
                    # Node D
                    if st_new == Gst.State.PLAYING:
                        update_status("D", True)
                    elif st_new < Gst.State.PLAYING:
                        update_status("D", False)

        return True

    bus.connect("message", on_message)

    pipeline.set_state(Gst.State.PLAYING)

    loop = GLib.MainLoop()

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Shutting down GStreamer pipeline...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
