#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstController", "1.0")
from gi.repository import Gst, GLib
import signal
import sys
import logging

# Configure logging.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Import the pipeline builders.
from audio_pipeline import build_audio_pipeline
from video_pipeline import build_video_pipeline

Gst.init(None)
main_loop = GLib.MainLoop()

# Dictionary to hold our pipelines.
# Keys: "audio", "video1", "video2"
pipelines = {}

# Global health counters for both audio and video endpoints.
health_counts = {
    "a_send_tn": 0, "a_send_dk": 0, "a_recv_tn": 0, "a_recv_dk": 0,
    "v_send_tn": 0, "v_send_dk": 0, "v_recv_tn": 0, "v_recv_dk": 0,
}

def pad_probe_callback(pad, info, probe_name):
    # Increment the counter for each buffer that passes.
    health_counts[probe_name] += 1
    return Gst.PadProbeReturn.OK

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
    return False  # Only run this timeout callback once.

def _do_restart(pipeline_name, pipeline_str):
    """
    Helper function called by the timeout callback to create and start a new pipeline.
    """
    new_pipeline = Gst.parse_launch(pipeline_str)
    bus = new_pipeline.get_bus()
    bus.add_signal_watch()
    # Use a lambda to pass the pipeline name into on_message.
    bus.connect("message", lambda bus, message, name=pipeline_name: on_message(bus, message, name))
    result = new_pipeline.set_state(Gst.State.PLAYING)
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to PLAYING.")
    pipelines[pipeline_name] = (new_pipeline, pipeline_str)
    logging.info(f"[{pipeline_name}] Pipeline restarted.")
    return False

def on_message(bus, message, pipeline_name):
    """
    Handle messages for each pipeline.
    Instead of quitting on EOS or ERROR, restart the failing pipeline.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream detected.")
        restart_pipeline(pipeline_name)
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"[{pipeline_name}] ERROR: {err}, Debug info: {debug}")
        restart_pipeline(pipeline_name)
    return True

def check_health():
    # Audio status block.
    audio_status = (
        "Audio:\n"
        f"Sending from Tunisia: {'Yes!' if health_counts['a_send_tn'] > 0 else 'No!'}\n"
        f"Sending from Denmark: {'Yes!' if health_counts['a_send_dk'] > 0 else 'No!'}\n"
        f"Receiving in Tunisia: {'Yes!' if health_counts['a_recv_tn'] > 0 else 'No!'}\n"
        f"Receiving in Denmark: {'Yes!' if health_counts['a_recv_dk'] > 0 else 'No!'}\n"
    )
    # Video status block.
    video_status = (
        "Video:\n"
        f"Sending from Tunisia: {'Yes!' if health_counts['v_send_tn'] > 0 else 'No!'}\n"
        f"Sending from Denmark: {'Yes!' if health_counts['v_send_dk'] > 0 else 'No!'}\n"
        f"Receiving in Tunisia: {'Yes!' if health_counts['v_recv_tn'] > 0 else 'No!'}\n"
        f"Receiving in Denmark: {'Yes!' if health_counts['v_recv_dk'] > 0 else 'No!'}\n"
    )
    status_str = audio_status + "\n" + video_status
    # Use ANSI escape codes to clear the screen and move the cursor to the top.
    print("\033[H\033[J" + status_str, end='', flush=True)
    
    # Reset counters.
    for key in health_counts:
        health_counts[key] = 0
    return True  # Continue running the timeout callback.

def signal_handler(sig, frame):
    logging.info("Interrupt received, stopping pipelines...")
    main_loop.quit()

def main():
    global pipelines
    # Build pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Should return a tuple (video_pipeline1, video_pipeline2)
    
    logging.info("Audio Pipeline:\n%s", audio_pipeline_str)
    logging.info("Video Pipeline 1:\n%s", video_pipeline_strs[0])
    logging.info("Video Pipeline 2:\n%s", video_pipeline_strs[1])
    
    # Create pipelines.
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
        bus.connect("message", lambda bus, message, name=name: on_message(bus, message, name))
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            logging.error(f"[{name}] Failed to set pipeline to PLAYING.")
    
    # ------------------------
    # Attach pad probes for health checking.
    # Audio endpoints:
    for key, element_name, pad_name, pad_type in [
        ("a_send_tn", "a_send_tn", "src", Gst.PadProbeType.BUFFER),
        ("a_send_dk", "a_send_dk", "src", Gst.PadProbeType.BUFFER),
        ("a_recv_tn", "a_recv_tn", "sink", Gst.PadProbeType.BUFFER),
        ("a_recv_dk", "a_recv_dk", "sink", Gst.PadProbeType.BUFFER),
    ]:
        elem = audio_pipeline.get_by_name(element_name)
        if elem:
            pad = elem.get_static_pad(pad_name)
            if pad:
                pad.add_probe(pad_type, lambda pad, info, probe_name=key: pad_probe_callback(pad, info, probe_name))
            else:
                logging.warning(f"Audio element '{element_name}' has no pad '{pad_name}'")
        else:
            logging.warning(f"Audio element '{element_name}' not found in pipeline.")
    
    # Video endpoints.
    # For video pipeline1:
    for key, element_name, pad_name, pipeline_key in [
        ("v_send_tn", "v_send_tn", "src", "video1"),
        ("v_recv_dk", "v_recv_dk", "sink", "video1"),
    ]:
        elem = pipelines[pipeline_key][0].get_by_name(element_name)
        if elem:
            pad = elem.get_static_pad(pad_name)
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, lambda pad, info, probe_name=key: pad_probe_callback(pad, info, probe_name))
            else:
                logging.warning(f"Video element '{element_name}' has no pad '{pad_name}'")
        else:
            logging.warning(f"Video element '{element_name}' not found in pipeline '{pipeline_key}'.")
    
    # For video pipeline2:
    for key, element_name, pad_name, pipeline_key in [
        ("v_send_dk", "v_send_dk", "src", "video2"),
        ("v_recv_tn", "v_recv_tn", "sink", "video2"),
    ]:
        elem = pipelines[pipeline_key][0].get_by_name(element_name)
        if elem:
            pad = elem.get_static_pad(pad_name)
            if pad:
                pad.add_probe(Gst.PadProbeType.BUFFER, lambda pad, info, probe_name=key: pad_probe_callback(pad, info, probe_name))
            else:
                logging.warning(f"Video element '{element_name}' has no pad '{pad_name}'")
        else:
            logging.warning(f"Video element '{element_name}' not found in pipeline '{pipeline_key}'.")
    
    # Set up a periodic health-check callback (every second).
    GLib.timeout_add_seconds(1, check_health)
    
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
