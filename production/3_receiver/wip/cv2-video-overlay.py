#!/usr/bin/env python3
import gi
import cv2
import numpy as np
from threading import Thread
import queue

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import os
import sys
import signal
import argparse

from config_loader import load_config

class VideoDifferencer(Thread):
    def __init__(self, people_path, background_queue):
        super().__init__()
        self.people_path = people_path
        self.background_queue = background_queue
        self.running = True
        self.frame = None

    def run(self):
        """Continuously read people.mp4 frames and update background from queue."""
        people = cv2.VideoCapture(self.people_path)

        # Attempt setting FPS to 25; note that for file-based sources,
        # OpenCV may not always honor this, depending on the container/codec.
        people.set(cv2.CAP_PROP_FPS, 25)

        # We won't block waiting for a single background frame.
        # Instead, we'll poll the queue each iteration.
        bg_frame = None

        while self.running:
            # Check if there's a newer background frame available
            while not self.background_queue.empty():
                bg_frame = self.background_queue.get_nowait()

            ret, frame = people.read()
            if not ret:
                # Reached end of file or error reading frame
                break

            # If we have a valid background frame, do the differencing
            if bg_frame is not None:
                # Resize both frames so they match in size
                frame_resized = cv2.resize(frame, (1920, 1080))
                bg_resized = cv2.resize(bg_frame, (1920, 1080))

                diff = cv2.absdiff(frame_resized, bg_resized)
                gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                _, mask = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)

                # Convert BGR -> RGBA by merging the mask as alpha
                b, g, r = cv2.split(frame_resized)
                rgba = cv2.merge((b, g, r, mask))

                # Update the internal frame that we push to GStreamer
                self.frame = rgba

        people.release()

    def stop(self):
        self.running = False

class VideoReceiver:
    def __init__(self, country):
        self.country = country
        self.pipeline = None
        self.loop = None
        self.server_address = None
        self.receive_port = None
        self.clock = None

        # This queue will be filled with background frames from the SRT feed.
        # The VideoDifferencer will continuously poll this queue for updates.
        self.background_queue = queue.Queue()

        # The differencer uses people.mp4 frames and compares them
        # with the streaming background frames from the queue.
        self.differencer = VideoDifferencer("people.mp4", self.background_queue)

    def build_pipeline(self):
        config = load_config()
        self.server_address = config.get("server_ip", "127.0.0.1")
        if self.country.lower() == "tn":
            self.receive_port = config.get("ports", {}).get("video_receive_tn")
        else:
            self.receive_port = config.get("ports", {}).get("video_receive_dk")

        pipeline_str = f"""
            compositor name=comp ! videoconvert ! kmssink sync=false

            appsrc name=difference_source is-live=true format=time 
                caps=video/x-raw,format=RGBA,width=1920,height=1080,framerate=25/1 
                ! queue 
                ! comp.sink_0

            srtsrc uri="srt://{self.server_address}:{self.receive_port}?mode=caller&latency=100" 
                ! queue max-size-time=2000000000 max-size-buffers=500 
                ! tsdemux name=demux 
                demux. ! queue ! h264parse config-interval=1 
                ! avdec_h264 
                ! videoconvert 
                ! videoscale 
                ! video/x-raw,width=1920,height=1080,framerate=25/1 
                ! tee name=live_tee
                live_tee. ! queue ! comp.sink_1
                live_tee. ! queue ! appsink name=bg_capture sync=false 
                    emit-signals=true max-buffers=1 drop=true
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("VideoReceiver: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"VideoReceiver: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def extract_background(self, sink):
        """Callback from appsink: each new frame is put into the background queue."""
        sample = sink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            caps = sample.get_caps()
            structure = caps.get_structure(0)
            width = structure.get_value("width")
            height = structure.get_value("height")

            result, mapinfo = buffer.map(Gst.MapFlags.READ)
            if result:
                frame = np.frombuffer(mapinfo.data, dtype=np.uint8).reshape((height, width, 3))
                # Put the new background frame into the queue
                self.background_queue.put(frame)
                buffer.unmap(mapinfo)
        # Return Gst.FlowReturn.OK to allow the appsink to continue
        return Gst.FlowReturn.OK

    def push_difference_frames(self, appsrc):
        """Push frames from the differencer (RGBA) into the GStreamer appsrc at ~25fps."""
        import time
        from gi.repository import Gst
        while self.differencer.running:
            frame = self.differencer.frame
            if frame is not None:
                data = frame.tobytes()
                buf = Gst.Buffer.new_allocate(None, len(data), None)
                buf.fill(0, data)
                # Each frame’s duration at 25fps
                buf.duration = Gst.util_uint64_scale_int(1, Gst.SECOND, 25)

                timestamp = getattr(self, 'timestamp', 0)
                buf.pts = buf.dts = timestamp
                buf.offset = timestamp
                self.timestamp = timestamp + buf.duration

                retval = appsrc.emit("push-buffer", buf)
                if retval != Gst.FlowReturn.OK:
                    print("Error pushing buffer to appsrc")

            # Sleep roughly 1/25 sec to match the framerate
            time.sleep(1/25)

    def run(self):
        pipeline_str = self.build_pipeline()
        print("VideoReceiver: Pipeline:\n", pipeline_str, "\n")

        self.pipeline = Gst.parse_launch(pipeline_str)
        if self.clock:
            self.pipeline.use_clock(self.clock)
        else:
            system_clock = Gst.SystemClock.obtain()
            self.pipeline.use_clock(system_clock)

        # Connect the appsink for continuous background frames
        appsink = self.pipeline.get_by_name("bg_capture")
        appsink.connect("new-sample", self.extract_background)

        # Set up bus callbacks
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        # Start pipeline
        self.pipeline.set_state(Gst.State.PLAYING)

        # Start the differencer thread
        self.differencer.start()

        # Set up our appsrc and push frames from the differencer
        appsrc = self.pipeline.get_by_name("difference_source")
        self.timestamp = 0

        Thread(target=self.push_difference_frames, args=(appsrc,), daemon=True).start()

        # Start the GLib main loop
        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"VideoReceiver: Exception -> {e}")
        finally:
            self.differencer.stop()
            self.pipeline.set_state(Gst.State.NULL)
            print("VideoReceiver: Pipeline stopped.")

    def stop(self):
        if self.loop:
            self.loop.quit()

def signal_handler(sig, frame, receiver):
    print("VideoReceiver: Interrupt received, stopping pipeline...")
    receiver.stop()
    sys.exit(0)

def main():
    Gst.init(None)
    parser = argparse.ArgumentParser(description="Video Receiver Script")
    parser.add_argument("--country", required=True, help="Country code (e.g., tn, dk)")
    args = parser.parse_args()

    receiver = VideoReceiver(args.country)

    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, receiver))
    signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(sig, frame, receiver))

    receiver.run()

if __name__ == "__main__":
    main()
