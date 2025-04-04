#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import signal
import sys
import os
import logging

# Configure logging.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Insert parent directory into Python path to import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

# Load the configuration.
cfg = load_config()

# Fetch the ports and audio parameters from the config.
video_send_tn = cfg.get("ports", {}).get("video_send_tn")
video_send_dk = cfg.get("ports", {}).get("video_send_dk")
audio_send_tn = cfg.get("ports", {}).get("audio_send_tn")
audio_send_dk = cfg.get("ports", {}).get("audio_send_dk")

audio_rate     = cfg.get("audio", {}).get("rate", 32000)
audio_channels = cfg.get("audio", {}).get("channels", 2)
encoding_name  = cfg.get("audio", {}).get("encoding_name", "L16")

# Set the output directory on the external SSD.
output_dir = "/mnt/tbdrive/video"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Build the pipeline strings.
# The file sinks now point to the external SSD output directory.
pipeline_str_tn = f"""
    srtsrc uri=srt://:{video_send_tn}?mode=listener&latency=100 !
      queue !
      decodebin !
      videoconvert !
      x264enc tune=zerolatency !
      queue !
      mux.
    srtsrc uri=srt://:{audio_send_tn}?mode=listener !
      queue !
      application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={audio_channels} !
      rtpL16depay !
      decodebin !
      audioconvert !
      voaacenc !
      queue !
      mux.
    mp4mux name=mux !
      filesink location={os.path.join(output_dir, "recorded_tn.mp4")}
"""

pipeline_str_dk = f"""
    srtsrc uri=srt://:{video_send_dk}?mode=listener&latency=100 !
      queue !
      decodebin !
      videoconvert !
      x264enc tune=zerolatency !
      queue !
      mux.
    srtsrc uri=srt://:{audio_send_dk}?mode=listener !
      queue !
      application/x-rtp,media=audio,clock-rate={audio_rate},encoding-name={encoding_name},channels={audio_channels} !
      rtpL16depay !
      decodebin !
      audioconvert !
      voaacenc !
      queue !
      mux.
    mp4mux name=mux !
      filesink location={os.path.join(output_dir, "recorded_dk.mp4")}
"""

# Dictionary to keep track of the pipelines.
pipelines = {}

def on_message(bus, message, pipeline_name):
    """
    Callback for bus messages. Logs EOS and ERROR messages.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream.")
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"[{pipeline_name}] Error: {err}, Debug info: {debug}")
    return True

def start_pipeline(pipeline_name, pipeline_str):
    """
    Create and start a GStreamer pipeline from a pipeline string.
    """
    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    # Pass the pipeline name into the message callback.
    bus.connect("message", lambda bus, message, name=pipeline_name: on_message(bus, message, name))
    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Unable to set pipeline to PLAYING.")
    pipelines[pipeline_name] = (pipeline, pipeline_str)
    logging.info(f"[{pipeline_name}] Recording pipeline started.")

def stop_pipelines():
    """
    Stop all recording pipelines.
    """
    for pipeline, _ in pipelines.values():
        pipeline.set_state(Gst.State.NULL)
    logging.info("Recording pipelines stopped.")

def signal_handler(sig, frame):
    """
    Handle signals to gracefully shut down the pipelines.
    """
    logging.info("Interrupt received, stopping recording pipelines...")
    stop_pipelines()
    sys.exit(0)

def run_recording():
    """
    Initialize GStreamer, start the recording pipelines, and run the GLib main loop.
    """
    Gst.init(None)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start the Tunisian and DK recording pipelines.
    start_pipeline("record_tn", pipeline_str_tn)
    start_pipeline("record_dk", pipeline_str_dk)

    # Create and run the main loop.
    main_loop = GLib.MainLoop()
    try:
        main_loop.run()
    except Exception as e:
        logging.error("Recording main loop error: %s", e)
    finally:
        stop_pipelines()

if __name__ == "__main__":
    run_recording()
