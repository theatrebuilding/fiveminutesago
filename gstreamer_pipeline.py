import gi
import yaml
import sys
import socketio
import os
import threading

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
        print(f"🔄 Updating status: {node} -> {'Connected' if is_connected else 'Disconnected'}")  # Debug Print

    connection_status[node] = is_connected
    sio.emit("update_status", connection_status)
    print(f"📤 Sent status update: {connection_status}")  # Debug Print


# ----- BUILD GStreamer PIPELINE -----
def build_pipeline(config):
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
      sink_0::always-ok=true
      sink_1::always-ok=true
      sink_1::active=true

    input-selector name=audio_selector_A
      sink_0::always-ok=true
      sink_1::always-ok=true
      sink_1::active=true

    input-selector name=video_selector_C
      sink_0::always-ok=true
      sink_1::always-ok=true
      sink_1::active=true

    input-selector name=audio_selector_C
      sink_0::always-ok=true
      sink_1::always-ok=true
      sink_1::active=true

    srtsrc uri={node_A_in} ! tsdemux name=demuxA
      demuxA. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_A.sink_0
      demuxA. ! queue ! opusdec ! audioconvert ! audio_selector_A.sink_0

    srtsrc uri={node_C_in} ! tsdemux name=demuxC
      demuxC. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_C.sink_0
      demuxC. ! queue ! opusdec ! audioconvert ! audio_selector_C.sink_0

    videotestsrc pattern={video_A_fallback} ! videoconvert ! video/x-raw,format=I420 ! video_selector_A.sink_1
    audiotestsrc wave={audio_A_fallback} ! audioconvert ! audio_selector_A.sink_1

    videotestsrc pattern={video_C_fallback} ! videoconvert ! video/x-raw,format=I420 ! video_selector_C.sink_1
    audiotestsrc wave={audio_C_fallback} ! audioconvert ! audio_selector_C.sink_1

    video_selector_A. ! videoconvert !
      x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} !
      h264parse ! queue ! mpegtsmux name=muxerA
    audio_selector_A. ! opusenc ! muxerA.
    muxerA. ! queue ! srtsink uri={node_B_out}

    video_selector_C. ! videoconvert !
      x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} !
      h264parse ! queue ! mpegtsmux name=muxerC
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
        print(f"📩 Received GStreamer Message: {msg.type}")  # Debug Print

        if msg.type == Gst.MessageType.STATE_CHANGED:
            src = msg.src
            if not src:
                return

            name = src.get_name()
            st_old, st_new, st_pending = msg.parse_state_changed()

            print(f"🔄 State changed for {name}: {st_old} -> {st_new}")  # Debug Print

            # Detect source elements (srtsrc = input, srtsink = output)
            if "srtsrc" in name.lower():
                if "7701" in name or "demuxa" in name.lower():
                    update_status("A", st_new == Gst.State.PLAYING)
                elif "7702" in name or "demuxc" in name.lower():
                    update_status("C", st_new == Gst.State.PLAYING)

            # Check state of SRT sinks
            elif "srtsink" in name.lower():
                if "8801" in name:
                    # Node B output
                    update_status("B", st_new == Gst.State.PLAYING)
                elif "8802" in name:
                    # Node D output
                    update_status("D", st_new == Gst.State.PLAYING)

        return True

    # Attach message handler
    bus.connect("message", on_message)

    # 🔥 Continuous monitoring to prevent dropped messages
    def watch_bus():
        while True:
            msg = bus.timed_pop_filtered(5000 * Gst.MSECOND, Gst.MessageType.ANY)
            if msg:
                on_message(bus, msg)

    threading.Thread(target=watch_bus, daemon=True).start()

    # Start pipeline
    pipeline.set_state(Gst.State.PLAYING)
    state_return = pipeline.get_state(5 * Gst.SECOND)
    
    print(f"🧐 Pipeline final state: {state_return.state}")  # Debugging
    
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
