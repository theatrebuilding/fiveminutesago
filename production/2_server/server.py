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
import datetime  # For timestamp generation

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

def _copy_file(src, pipeline_label, msg_prefix=""):
    """
    Helper function that copies a file (using sudo cp) to the /tbdrive/video directory.
    The destination filename is constructed as:
        {original_name}_{YYYYMMDDHHMMSS}.{extension}
    This function will keep retrying until the copy is successful.
    """
    dest_dir = "/mnt/tbdrive/video"
    base, ext = os.path.splitext(os.path.basename(src))
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    dest_filename = f"{base}_{timestamp}{ext}"
    dest_path = os.path.join(dest_dir, dest_filename)
    logging.info(f"[{pipeline_label}] {msg_prefix}Copying file from {src} to {dest_path}...")

    copy_successful = False
    while not copy_successful:
        try:
            result = subprocess.run(["sudo", "cp", src, dest_path],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                copy_successful = True
                logging.info(f"[{pipeline_label}] File copy successful.")
            else:
                logging.error(f"[{pipeline_label}] File copy failed with return code {result.returncode}. Retrying in 3 seconds...")
                logging.error(f"[{pipeline_label}] cp stderr: {result.stderr}")
                time.sleep(3)
        except Exception as e:
            logging.error(f"[{pipeline_label}] Exception during file copy: {e}. Retrying in 3 seconds...")
            time.sleep(3)

def restart_pipeline(pipeline_name):
    """
    Restart the pipeline for a given key.
    This function sets the failing pipeline to NULL and, after a delay,
    recreates it.
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
    # Use a lambda to pass the pipeline name into the on_message callback.
    bus.connect("message", lambda bus, message, name=pipeline_name: on_message(bus, message, name))
    result = new_pipeline.set_state(Gst.State.PLAYING)
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to PLAYING.")
    pipelines[pipeline_name] = (new_pipeline, pipeline_str)
    logging.info(f"[{pipeline_name}] Pipeline restarted.")
    return False  # Stop the timeout callback.

def copy_file_and_restart(pipeline_name, restart_callback):
    """
    For a given video pipeline, copy the recorded file (with a timestamp appended)
    before scheduling a pipeline restart.
    """
    # Identify the source file.
    if pipeline_name == "video1":
        src = recorded_file_tn
    elif pipeline_name == "video2":
        src = recorded_file_dk
    else:
        logging.error(f"[{pipeline_name}] Not a video pipeline, no file copy needed.")
        GLib.idle_add(restart_callback, pipeline_name)
        return

    _copy_file(src, pipeline_name, msg_prefix="Pre-restart: ")

    # Once the copy is successful, schedule the pipeline restart on the main loop.
    GLib.idle_add(restart_callback, pipeline_name)

def copy_video_files_on_exit():
    """
    Copies both video pipeline files (with a timestamp appended to each) before shutdown.
    This ensures that, even when you Ctrl+C the script, the recorded files are safely copied.
    """
    logging.info("Copying video pipeline files on shutdown...")
    _copy_file(recorded_file_tn, "video1_exit", msg_prefix="On shutdown: ")
    _copy_file(recorded_file_dk, "video2_exit", msg_prefix="On shutdown: ")

def on_message(bus, message, pipeline_name):
    """
    Handle messages for each pipeline.
    Instead of quitting on EOS or ERROR, restart the failing pipeline.
    For video pipelines, ensure that the recorded file is copied to /tbdrive/video
    before the pipeline is restarted.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream detected.")
        if pipeline_name.startswith("video"):
            logging.info(f"[{pipeline_name}] Initiating file copy before restart due to EOS.")
            # Spawn a thread to perform the file copy and then schedule a restart.
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
    """
    When a SIGINT or SIGTERM is received (for example via Ctrl+C),
    log the event and quit the main loop.
    """
    logging.info("Interrupt received, preparing to shut down...")
    main_loop.quit()

def main():
    global pipelines
    # Build the pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Expects a tuple: (video_pipeline1, video_pipeline2)

    logging.info("Audio Pipeline:\n%s", audio_pipeline_str)
    logging.info("Video Pipeline 1:\n%s", video_pipeline_strs[0])
    logging.info("Video Pipeline 2:\n%s", video_pipeline_strs[1])

    # Create pipelines and store them.
    audio_pipeline = Gst.parse_launch(audio_pipeline_str)
    video_pipeline1 = Gst.parse_launch(video_pipeline_strs[0])
    video_pipeline2 = Gst.parse_launch(video_pipeline_strs[1])
    pipelines["audio"] = (audio_pipeline, audio_pipeline_str)
    pipelines["video1"] = (video_pipeline1, video_pipeline_strs[0])
    pipelines["video2"] = (video_pipeline2, video_pipeline_strs[1])

    # Set up bus watches for each pipeline.
    for name, (pipeline, _) in pipelines.items():
        bus = pipeline.get_bus()
        bus.add_signal_watch()
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
        # On shutdown, copy the video files even if termination is via Ctrl+C.
        copy_video_files_on_exit()
        # Now clean up all pipelines.
        for pipeline, _ in pipelines.values():
            pipeline.set_state(Gst.State.NULL)
        logging.info("Pipelines stopped.")

if __name__ == "__main__":
    main()
