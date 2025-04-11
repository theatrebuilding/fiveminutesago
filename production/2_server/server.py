#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib
import signal
import sys
import logging
import subprocess
import threading
import time
import os
import datetime  # Import datetime for timestamp generation

# Configure logging.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Import the pipeline builders.
from audio_pipeline import build_audio_pipeline
from video_pipeline import build_video_pipeline

# Recorded file paths used in the video pipelines.
recorded_file_tn = "/mnt/tbdrive/video_tn.ts"
recorded_file_dk = "/mnt/tbdrive/video_dk.ts"

Gst.init(None)
main_loop = GLib.MainLoop()

# A dictionary to hold our pipelines along with their pipeline strings.
pipelines = {}

def restart_pipeline(pipeline_name):
    """
    Restart the pipeline for a given key.
    This function sets the failing pipeline to NULL and, after a delay, recreates it.
    """
    pipeline, pipeline_str = pipelines[pipeline_name]
    logging.info(f"[{pipeline_name}] Restarting pipeline...")
    result = pipeline.set_state(Gst.State.NULL)  # Stop the current pipeline.
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to NULL.")
    # Restart after a delay (e.g., 3 seconds).
    GLib.timeout_add_seconds(3, _do_restart, pipeline_name, pipeline_str)
    return False  # Stop the timeout callback.

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

def copy_file_and_restart(pipeline_name, restart_callback):
    """
    Copy the recorded file to a new location with a timestamp appended to the file name.
    This function uses 'sudo cp' to copy the file and will retry until successful.
    Once the file is successfully copied, it schedules the pipeline restart.
    """
    # Determine the source file based on the pipeline name.
    if pipeline_name == "video1":
        src = recorded_file_tn
    elif pipeline_name == "video2":
        src = recorded_file_dk
    else:
        logging.error(f"[{pipeline_name}] Not a video pipeline, no file copy needed.")
        # Schedule an immediate restart.
        GLib.idle_add(restart_callback, pipeline_name)
        return

    dest_dir = "/tbdrive/video"
    # Construct a new file name with a timestamp appended.
    base, ext = os.path.splitext(os.path.basename(src))
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    dest_filename = f"{base}_{timestamp}{ext}"
    dest_path = os.path.join(dest_dir, dest_filename)

    logging.info(f"[{pipeline_name}] Copying file from {src} to {dest_path} before pipeline restart...")

    copy_successful = False
    while not copy_successful:
        try:
            result = subprocess.run(["sudo", "cp", src, dest_path],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                copy_successful = True
                logging.info(f"[{pipeline_name}] File copy successful.")
            else:
                logging.error(f"[{pipeline_name}] File copy failed with return code {result.returncode}. Retrying in 3 seconds...")
                logging.error(f"[{pipeline_name}] cp stderr: {result.stderr}")
                time.sleep(3)
        except Exception as e:
            logging.error(f"[{pipeline_name}] Exception during file copy: {e}. Retrying in 3 seconds...")
            time.sleep(3)
    
    # Once the copy is successful, schedule the pipeline restart on the main loop.
    GLib.idle_add(restart_callback, pipeline_name)

def on_message(bus, message, pipeline_name):
    """
    Handle messages for each pipeline.
    Instead of quitting the main loop on EOS or ERROR, we restart the failing pipeline.
    For video pipelines, ensure that the recorded file is copied to /tbdrive/video
    before the pipeline is restarted.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream detected.")
        if pipeline_name.startswith("video"):
            logging.info(f"[{pipeline_name}] Initiating file copy before restart due to EOS.")
            # Spawn a thread to copy the file then schedule a restart.
            threading.Thread(target=copy_file_and_restart, args=(pipeline_name, restart_pipeline), daemon=True).start()
        else:
            restart_pipeline(pipeline_name)
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"[{pipeline_name}] ERROR: {err}, Debug info: {debug}")
        if pipeline_name.startswith("video"):
            logging.info(f"[{pipeline_name}] Initiating file copy before restart due to error.")
            threading.Thread(target=copy_file_and_restart, args=(pipeline_name, restart_pipeline), daemon=True).start()
        else:
            restart_pipeline(pipeline_name)
    return True  # Continue receiving messages.

def signal_handler(sig, frame):
    logging.info("Interrupt received, stopping pipelines...")
    main_loop.quit()

def main():
    global pipelines
    # Build the pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Returns a tuple: (video_pipeline1, video_pipeline2)

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

    # Set up a bus watch for each pipeline.
    for name, (pipeline, _) in pipelines.items():
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        # Use a lambda to pass the pipeline name into the callback.
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
