#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import signal
import sys
import logging
import subprocess
import concurrent.futures
import os

# Insert parent directory to access config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

# Set up logging.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Load configuration.
from config_loader import load_config
cfg = load_config()

# Import your pipeline build functions.
from audio_pipeline import build_audio_pipeline
from video_pipeline import build_video_pipeline

# Initialize GStreamer and the GLib main loop.
Gst.init(None)
main_loop = GLib.MainLoop()

# Dictionary to hold our pipelines.
# Keys: "audio", "video1", "video2"
pipelines = {}

# Build a mapping of endpoint names to their port numbers.
# (Adjust these keys/names as needed for your environment.)
endpoints = {
    "a_send_tn": cfg.get("ports", {}).get("audio_send_tn"),
    "a_send_dk": cfg.get("ports", {}).get("audio_send_dk"),
    "a_recv_tn": cfg.get("ports", {}).get("audio_receive_tn"),
    "a_recv_dk": cfg.get("ports", {}).get("audio_receive_dk"),
    "v_send_tn": cfg.get("ports", {}).get("video_send_tn"),
    "v_send_dk": cfg.get("ports", {}).get("video_send_dk"),
    "v_recv_tn": cfg.get("ports", {}).get("video_receive_tn"),
    "v_recv_dk": cfg.get("ports", {}).get("video_receive_dk"),
}

def restart_pipeline(pipeline_name):
    """
    Restart the given pipeline by setting it to NULL and re-launching it after a delay.
    """
    pipeline, pipeline_str = pipelines[pipeline_name]
    logging.info(f"[{pipeline_name}] Restarting pipeline...")
    pipeline.set_state(Gst.State.NULL)
    GLib.timeout_add_seconds(3, _do_restart, pipeline_name, pipeline_str)
    return False

def _do_restart(pipeline_name, pipeline_str):
    new_pipeline = Gst.parse_launch(pipeline_str)
    bus = new_pipeline.get_bus()
    bus.add_signal_watch()
    # Pass the pipeline name to on_message via a lambda.
    bus.connect("message", lambda bus, message, name=pipeline_name: on_message(bus, message, name))
    result = new_pipeline.set_state(Gst.State.PLAYING)
    if result == Gst.StateChangeReturn.FAILURE:
        logging.error(f"[{pipeline_name}] Failed to set pipeline to PLAYING.")
    pipelines[pipeline_name] = (new_pipeline, pipeline_str)
    logging.info(f"[{pipeline_name}] Pipeline restarted.")
    return False

def on_message(bus, message, pipeline_name):
    """
    Restart a pipeline if EOS or ERROR is encountered.
    """
    msg_type = message.type
    if msg_type == Gst.MessageType.EOS:
        logging.info(f"[{pipeline_name}] End of stream detected.")
        restart_pipeline(pipeline_name)
    elif msg_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        logging.error(f"[{pipeline_name}] ERROR: {err}, Debug: {debug}")
        restart_pipeline(pipeline_name)
    return True

def check_port(endpoint, port):
    """
    Run tcpdump to check for activity on the specified port.
    Returns True if a packet is captured, False otherwise.
    """
    try:
        result = subprocess.run(
            ["tcpdump", "-c", "1", "-i", "any", "port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1
        )
        return (result.returncode == 0)
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        logging.error(f"Error checking port {port} for endpoint {endpoint}: {e}")
        return False

def health_check():
    """
    Check each endpoint concurrently using tcpdump and then update the console output.
    """
    statuses = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        future_to_ep = {executor.submit(check_port, ep, port): ep 
                        for ep, port in endpoints.items() if port}
        for future in concurrent.futures.as_completed(future_to_ep):
            ep = future_to_ep[future]
            try:
                statuses[ep] = future.result()
            except Exception:
                statuses[ep] = False

    # Build the status strings.
    audio_status = (
        "Audio:\n"
        f"Sending from Tunisia: {'Yes!' if statuses.get('a_send_tn', False) else 'No!'}\n"
        f"Sending from Denmark: {'Yes!' if statuses.get('a_send_dk', False) else 'No!'}\n"
        f"Receiving in Tunisia: {'Yes!' if statuses.get('a_recv_tn', False) else 'No!'}\n"
        f"Receiving in Denmark: {'Yes!' if statuses.get('a_recv_dk', False) else 'No!'}\n"
    )
    video_status = (
        "Video:\n"
        f"Sending from Tunisia: {'Yes!' if statuses.get('v_send_tn', False) else 'No!'}\n"
        f"Sending from Denmark: {'Yes!' if statuses.get('v_send_dk', False) else 'No!'}\n"
        f"Receiving in Tunisia: {'Yes!' if statuses.get('v_recv_tn', False) else 'No!'}\n"
        f"Receiving in Denmark: {'Yes!' if statuses.get('v_recv_dk', False) else 'No!'}\n"
    )
    output = audio_status + "\n" + video_status

    # Clear the screen and print the new status block.
    print("\033[H\033[J" + output, end='', flush=True)
    return True

def signal_handler(sig, frame):
    logging.info("Interrupt received, stopping pipelines...")
    main_loop.quit()

def main():
    global pipelines
    # Build pipeline strings.
    audio_pipeline_str = build_audio_pipeline()
    video_pipeline_strs = build_video_pipeline()  # Should return a tuple: (video_pipeline1, video_pipeline2)

    logging.info("Audio Pipeline:\n%s", audio_pipeline_str)
    logging.info("Video Pipeline 1:\n%s", video_pipeline_strs[0])
    logging.info("Video Pipeline 2:\n%s", video_pipeline_strs[1])

    # Create and store pipelines.
    audio_pipeline = Gst.parse_launch(audio_pipeline_str)
    video_pipeline1 = Gst.parse_launch(video_pipeline_strs[0])
    video_pipeline2 = Gst.parse_launch(video_pipeline_strs[1])
    pipelines["audio"] = (audio_pipeline, audio_pipeline_str)
    pipelines["video1"] = (video_pipeline1, video_pipeline_strs[0])
    pipelines["video2"] = (video_pipeline2, video_pipeline_strs[1])

    # Set up bus watches for pipeline restart on EOS or ERROR.
    for name, (pipeline, _) in pipelines.items():
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", lambda bus, message, name=name: on_message(bus, message, name))
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            logging.error(f"[{name}] Failed to set pipeline to PLAYING.")

    # Schedule the periodic health check (every second).
    GLib.timeout_add_seconds(1, health_check)

    # Set up signal handlers.
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        main_loop.run()
    except Exception as e:
        logging.error("Main loop error: %s", e)
    finally:
        for pipeline, _ in pipelines.values():
            pipeline.set_state(Gst.State.NULL)
        logging.info("Pipelines stopped.")

if __name__ == "__main__":
    main()
