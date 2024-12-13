import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

def gstreamer_receiver(port):
    # Initialize GStreamer
    Gst.init(None)

    # This pipeline:
    # 1. Listens on `port` for TCP connections.
    # 2. Receives an MPEG-TS stream containing H.264.
    # 3. Demuxes the TS, parses H.264, decodes it, then sends it to fakesink.
    # Using fakesink means it won't display anything, but it will still verify
    # that data is being received and processed.
    pipeline_description = (
        f"tcpserversrc port={port} ! tsdemux name=demux "
        "demux. ! queue ! h264parse ! avdec_h264 ! fakesink"
    )

    pipeline = Gst.parse_launch(pipeline_description)

    # Start playing
    pipeline.set_state(Gst.State.PLAYING)

    # Main loop for handling GStreamer events
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    
    def on_message(bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Error: {err.message}")
            print(f"Debug info: {debug}")
            loop.quit()
        elif msg_type == Gst.MessageType.EOS:
            print("End-Of-Stream reached")
            loop.quit()
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                print(f"Pipeline state changed from {old_state.value_name} to {new_state.value_name}")

    bus.connect("message", on_message)

    try:
        print(f"Starting GStreamer receiver on port {port}...")
        loop.run()
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    # Make sure this matches the sender's port.
    gstreamer_receiver(port=8000)
