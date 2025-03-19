#!/usr/bin/env python3
import gi
import sys

# Initialize GStreamer
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

Gst.init(None)

# Configuration parameters
SRT_SERVER = "178.249.52.14"
SEND_PORT = 7701

# Video source and encoding parameters
video_src = "v4l2src device=/dev/video0"
color_format = "I420"
tune = "zerolatency"
bitrate = 1000
key_int_max = 15
bframes = 0
aud = "true"
byte_stream = "true"
option_str = ""
config_interval = 1
alignment = 7

# Construct SRT URI
srt_uri = f"srt://{SRT_SERVER}:{SEND_PORT}?mode=caller&latency=500&rbuf=327680"

# GStreamer pipeline command
PIPELINE_CMD = (
    f"{video_src} ! videoconvert ! videorate ! "
    f"x264enc bitrate=1000 tune=zerolatency key-int-max=15 bframes=0 aud=true byte-stream=true option-string=\"\" ! "
    f"video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline ! "
    f"h264parse config-interval=1 ! queue ! mpegtsmux alignment={alignment} ! "
    f"srtsink uri=\"{srt_uri}\""
)

def main():
    print("Launching video sender pipeline...")
    pipeline = Gst.parse_launch(PIPELINE_CMD)
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"GStreamer ERROR: {err}, debug: {dbg}")
        elif msg.type == Gst.MessageType.EOS:
            print("End-of-stream reached.")
            loop.quit()

    bus.connect("message", on_message)

    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("Stopping pipeline...")
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")

if __name__ == "__main__":
    main()
