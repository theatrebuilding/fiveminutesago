#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib
import signal
import sys
import logging  # new import

# Configure logging.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Import the pipeline builders.
from audio_pipeline import build_audio_pipeline
from video_pipeline import build_video_pipeline

Gst.init(None)
main_loop = GLib.MainLoop()

# A dictionary to hold our pipelines along with their pipeline string.
# Keys are pipeline names.
pipelines = {}

def restart_pipeline(pipeline_name):
    """
    Restart the pipeline for a given key.
    This function sets the failing pipeline to NULL, and after a delay, recreates it.
    """
    pipeline, pipeline_str = pipelines[pipeline_name]
    logging.info(f"[{pipeline_name}] Restarting pipeline...")
    result = pipeline.set_state(Gst.State.NULL)  # Stop the current pipeline.
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to NULL.")
    # Restart after a delay (e.g., 3 seconds).
    GLib.timeout_add_seconds(3, _do_restart, pipeline_name, pipeline_str)
    # Return False so the timeout callback is only run once.
    return False

def _do_restart(pipeline_name, pipeline_str):
    """
    Helper function called by the timeout callback to create and start a new pipeline.
    """
    new_pipeline = Gst.parse_launch(pipeline_str)
    # Add bus watch for the new pipeline.
    bus = new_pipeline.get_bus()
    bus.add_signal_watch()
    # Use a lambda to pass the pipeline name into on_message.
    bus.connect("message", lambda bus, message, name=pipeline_name: on_message(bus, message, name))
    result = new_pipeline.set_state(Gst.State.PLAYING)
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to PLAYING.")
    pipelines[pipeline_name] = (new_pipeline, pipeline_str)
    logging.info(f"[{pipeline_name}] Pipeline restarted.")
    return False  # Stop the timeout callback.

def on_message(bus, message, pipeline_name):
    """
    Handle messages for each pipeline.
    Instead of quitting the main loop on EOS or ERROR, we restart the failing pipeline.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream detected.")
        restart_pipeline(pipeline_name)
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"[{pipeline_name}] ERROR: {err}, Debug info: {debug}")
        restart_pipeline(pipeline_name)
    return True  # Continue receiving messages.

def signal_handler(sig, frame):
    logging.info("Interrupt received, stopping pipelines...")
    main_loop.quit()

def main():
    global pipelines
    # Build the pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Returns a tuple (video_pipeline1, video_pipeline2)

    logging.info("Audio Pipeline:\n%s", audio_pipeline_str)
    logging.info("Video Pipeline 1:\n%s", video_pipeline_strs[0])
    logging.info("Video Pipeline 2:\n%s", video_pipeline_strs[1])

    # Create pipelines and store them in our dictionary.
    audio_pipeline = Gst.parse_launch(audio_pipeline_str)
    video_pipeline1 = Gst.parse_launch(video_pipeline_strs[0])
    video_pipeline2 = Gst.parse_launch(video_pipeline_strs[1])
    pipelines["audio"] = (audio_pipeline, audio_pipeline_str)
    pipelines["video1"] = (video_pipeline1, video_pipeline_strs[0])
    pipelines["video2"] = (video_pipeline2, video_pipeline_strs[1])

    # Set up bus watch for each pipeline.
    for name, (pipeline, _) in pipelines.items():
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        # Use lambda to pass the pipeline name into the callback.
        bus.connect("message", lambda bus, message, name=name: on_message(bus, message, name))
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            logging.error(f"[{name}] Failed to set pipeline to PLAYING.")

    # Set up signal handlers.
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        main_loop.run()
    except Exception as e:
        logging.error("Main loop error: %s", e)
    finally:
        # Clean up all pipelines.
        for pipeline, _ in pipelines.values():
            pipeline.set_state(Gst.State.NULL)
        logging.info("Pipelines stopped.")

if __name__ == "__main__":
    main()
