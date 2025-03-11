import subprocess
import os
import signal
import time
from datetime import datetime

# Create recordings directory if it doesn't exist
os.makedirs("recordings", exist_ok=True)

# Global variables to track processes
pipeline_process = None
recording_process = None

def start_pipeline():
    """Starts the GStreamer pipeline for audio mixing and forwarding to port 8802."""
    global pipeline_process
    print("🔄 Starting audio mixing pipeline...")

    pipeline_cmd = [
        "gst-launch-1.0", "-v",
        "srtsrc", "uri=srt://:8801?mode=listener", "!",
        "queue", "!",
        "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2", "!",
        "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!",
        "queue", "!", "mixer.",
        "srtsrc", "uri=srt://:8803?mode=listener", "!",
        "queue", "!",
        "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2", "!",
        "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!",
        "queue", "!", "mixer.",
        "audiomixer", "name=mixer", "!",
        "audioconvert", "!", "audioresample", "!",
        "audio/x-raw,format=S16BE,channels=2,rate=32000", "!",
        "rtpL16pay", "!", "srtsink", "uri=srt://:8802?mode=listener", "wait-for-connection=false"
    ]

    pipeline_process = subprocess.Popen(pipeline_cmd)
    print("✅ Audio pipeline started.")

def start_recording():
    """Records audio from SRT stream on port 8802 into chunks."""
    global recording_process
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"recordings/audio_chunk_{timestamp}.mp3"

        print(f"🔴 Recording: {filename}")

        recording_cmd = [
            "gst-launch-1.0", "-q",
            "srtsrc", "uri=srt://:8802?mode=listener", "!",
            "queue", "!",
            "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!",
            "lamemp3enc", "target=1", "bitrate=192", "cbr=true", "!",
            "filesink", f"location={filename}"
        ]

        recording_process = subprocess.Popen(recording_cmd)

        # Record for the specified chunk duration
        time.sleep(60)  # Adjust chunk duration here

        # Stop current recording
        recording_process.terminate()
        recording_process.wait()

def stop_processes(signal_received, frame):
    """Handles Ctrl+C to stop everything gracefully."""
    global pipeline_process, recording_process
    print("\n🛑 Stopping processes...")

    if pipeline_process:
        pipeline_process.terminate()
        pipeline_process.wait()

    if recording_process:
        recording_process.terminate()
        recording_process.wait()

    print("✅ All processes stopped.")
    exit(0)

# Attach signal handler for Ctrl+C
signal.signal(signal.SIGINT, stop_processes)

if __name__ == "__main__":
    try:
        start_pipeline()
        time.sleep(3)  # Allow pipeline to stabilize before recording
        start_recording()
    except KeyboardInterrupt:
        stop_processes(None, None)
