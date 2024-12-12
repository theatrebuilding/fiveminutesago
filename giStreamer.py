import gi
import sys
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

def gstreamer_receiver():
    # Initialize GStreamer
    Gst.init(None)

    # Build the pipeline
    pipeline_description = (
        "tcpserversrc port=8000 ! queue ! "
        "application/x-rtp,media=video,encoding-name=H264,payload=96 "
        "! rtph264depay ! tee name=t "
        "t. ! queue ! rtph264pay ! tcpserversink port=9000 recover-policy=keyframe "
        "t. ! queue ! rtph264pay ! tcpserversink port=9001 recover-policy=keyframe"
    )

    pipeline = Gst.parse_launch(pipeline_description)

    # Start playing
    pipeline.set_state(Gst.State.PLAYING)
    print("Playing...")

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

    bus.connect("message", on_message)

    try:
        print("Starting GStreamer receiver...")
        loop.run()
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    gstreamer_receiver()
