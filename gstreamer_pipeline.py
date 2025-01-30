import gi
import yaml
import sys
import socketio
import os
import threading
import time

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

connection_status = {
    "A": False,  # Node A input
    "C": False,  # Node C input
    "B": False,  # Node B output
    "D": False   # Node D output
}

def update_status(node, is_connected: bool):
    """Update local dictionary and emit to the Flask dashboard."""
    global connection_status

    if connection_status[node] != is_connected:
        print(f"🔄 Updating status: {node} -> {'Connected' if is_connected else 'Disconnected'}")

    connection_status[node] = is_connected
    sio.emit("update_status", connection_status)
    print(f"📤 Sent status update: {connection_status}")

# ----- BUILD GStreamer PIPELINE -----
def build_pipeline(config):
    node_A_in = config["srt"]["input"]["node_A"]["uri"]
    node_C_in = config["srt"]["input"]["node_C"]["uri"]
    node_B_out = config["srt"]["output"]["node_B"]["uri"]
    node_D_out = config["srt"]["output"]["node_D"]["uri"]

    pipeline_str = f"""
    srtsrc uri={node_A_in} do-timestamp=true ! tsdemux name=demuxA
      demuxA. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! h264parse ! avdec_h264 ! videoconvert ! x264enc tune=zerolatency bitrate=1500 key-int-max=30 ! h264parse ! queue ! mpegtsmux name=muxerA
      demuxA. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! opusdec ! audioconvert ! opusenc ! muxerA.
    muxerA. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! srtsink uri={node_B_out}

    srtsrc uri={node_C_in} do-timestamp=true ! tsdemux name=demuxC
      demuxC. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! h264parse ! avdec_h264 ! videoconvert ! x264enc tune=zerolatency bitrate=1500 key-int-max=30 ! h264parse ! queue ! mpegtsmux name=muxerC
      demuxC. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! opusdec ! audioconvert ! opusenc ! muxerC.
    muxerC. ! queue max-size-buffers=500 max-size-time=2000000000 leaky=2 ! srtsink uri={node_D_out}
    """
    return pipeline_str

def monitor_pipeline(pipeline):
    """Monitor pipeline state and report packet flow every 5 seconds."""
    while True:
        state = pipeline.get_state(1 * Gst.SECOND).state
        print(f"📡 Pipeline State: {state}")

        # Query elements for buffer levels
        for node, pad_name in [("A", "demuxA"), ("C", "demuxC"), ("B", "muxerA"), ("D", "muxerC")]:
            element = pipeline.get_by_name(pad_name)
            if element:
                query = Gst.Query.new_buffering(Gst.Format.BUFFERS)
                if element.query(query):
                    _, _, _, buffers = query.parse_buffering_range()
                    print(f"🔎 Node {node}: {buffers} buffers queued")
                    update_status(node, buffers > 0)  # Mark node as connected if buffers > 0
                else:
                    update_status(node, False)  # Mark as disconnected if query fails

        time.sleep(5)  # Wait 5 seconds before next check

def main():
    config = load_config()
    pipeline_str = build_pipeline(config)

    print("🚀 Starting GStreamer pipeline with config:\n", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    # ----- MESSAGE HANDLER -----
    def on_message(bus, msg):
        print(f"📩 Received GStreamer Message: {msg.type}")

        if msg.type == Gst.MessageType.STATE_CHANGED:
            src = msg.src
            if not src:
                return

            name = src.get_name()
            st_old, st_new, st_pending = msg.parse_state_changed()
            print(f"🔄 State changed for {name}: {st_old} -> {st_new}")

            if "srtsrc" in name.lower():
                if "7701" in name or "demuxa" in name.lower():
                    update_status("A", st_new == Gst.State.PLAYING)
                elif "7702" in name or "demuxc" in name.lower():
                    update_status("C", st_new == Gst.State.PLAYING)
            elif "srtsink" in name.lower():
                if "8801" in name:
                    update_status("B", st_new == Gst.State.PLAYING)
                elif "8802" in name:
                    update_status("D", st_new == Gst.State.PLAYING)

        return True

    # Attach message handler
    bus.connect("message", on_message)

    # 🔥 Background thread to continuously monitor the pipeline
    threading.Thread(target=monitor_pipeline, args=(pipeline,), daemon=True).start()

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
