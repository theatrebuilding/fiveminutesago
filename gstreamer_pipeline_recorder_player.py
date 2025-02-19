import gi
import yaml
import os
import sys
import signal
import time
import glob
from datetime import datetime
from threading import Thread

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

CONFIG_FILE = "config.yaml"
RECORDINGS_DIR = "recordings"
CHUNK_DURATION = 60  # Change this to adjust recording duration (seconds)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: Config file '{CONFIG_FILE}' not found.")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def on_message(bus, message):
    t = message.type
    if t == Gst.MessageType.EOS:
        print("End of stream")
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Error: {err}, Debug info: {debug}")


def build_pipeline(cfg):
    """Builds the main GStreamer pipeline (Video & Audio)."""
    srt_cfg = cfg["srt"]

    srt_video_src = srt_cfg.get("video_src", "srt://:7701?mode=listener")
    srt_video_sink = srt_cfg.get("video_sink", "srt://:7702?mode=listener")
    srt_audio_src = srt_cfg.get("audio_src", "srt://:8801?mode=listener")
    srt_audio_sink = srt_cfg.get("audio_sink", "srt://:8802?mode=listener")

    pipeline_str = f"""
    srtsrc uri="{srt_video_src}" ! queue ! srtsink uri="{srt_video_sink}"
    srtsrc uri="{srt_audio_src}" ! queue ! srtsink uri="{srt_audio_sink}"
    """

    return pipeline_str, srt_audio_src, srt_audio_sink


def get_audio_recording_pipeline():
    """Returns a GStreamer pipeline string to record the SRT audio stream into an MP3 file."""
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"{RECORDINGS_DIR}/audio_chunk_{timestamp}.mp3"

    pipeline_str = f"""
    srtsrc uri="srt://:8801?mode=listener" ! queue !
    decodebin ! audioconvert ! audioresample ! lamemp3enc target=1 bitrate=192 !
    filesink location={output_file}
    """

    print(f"Recording started: {output_file}")
    return pipeline_str, output_file


def start_audio_recording():
    """Starts recording audio in chunks."""
    while True:
        pipeline_str, output_file = get_audio_recording_pipeline()
        recording_pipeline = Gst.parse_launch(pipeline_str)

        recording_pipeline.set_state(Gst.State.PLAYING)
        time.sleep(CHUNK_DURATION)

        recording_pipeline.set_state(Gst.State.NULL)
        print(f"Recording saved: {output_file}")


def playback_recordings(audio_sink):
    """Continuously plays recorded audio files, mixing with the live stream."""
    while True:
        recordings = sorted(glob.glob(f"{RECORDINGS_DIR}/*.mp3"))

        if not recordings:
            print("No recordings found, waiting...")
            time.sleep(10)  # Wait before checking again
            continue

        for file in recordings:
            print(f"Playing recording: {file}")

            playback_pipeline_str = f"""
            filesrc location="{file}" ! decodebin ! audioconvert ! audioresample !
            audiomixer name=mix !
            queue ! opusenc ! rtpopuspay ! srtsink uri="srt://:8802?mode=caller"
            srtsrc uri="srt://:8801?mode=listener" ! decodebin ! audioconvert ! audioresample ! mix.
            """

            playback_pipeline = Gst.parse_launch(playback_pipeline_str)
            playback_pipeline.set_state(Gst.State.PLAYING)

            time.sleep(CHUNK_DURATION)  # Wait for the duration of the chunk
            playback_pipeline.set_state(Gst.State.NULL)

        time.sleep(5)  # Small delay before looping again


def signal_handler(sig, frame):
    print("Interrupt received, stopping pipeline...")
    loop.quit()


def main():
    global loop
    cfg = load_config()
    pipeline_str, srt_audio_src, srt_audio_sink = build_pipeline(cfg)

    print("GStreamer pipeline:\n", pipeline_str, "\n")

    # Start main streaming pipeline (video only)
    pipeline = Gst.parse_launch(pipeline_str)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message)
    pipeline.set_state(Gst.State.PLAYING)

    # Start audio recording thread
    recording_thread = Thread(target=start_audio_recording, daemon=True)
    recording_thread.start()

    # Start playback thread for recordings
    playback_thread = Thread(target=playback_recordings, args=(srt_audio_sink,), daemon=True)
    playback_thread.start()

    loop = GLib.MainLoop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped.")


if __name__ == "__main__":
    main()
