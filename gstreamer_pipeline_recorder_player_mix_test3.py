import subprocess
import time
import os
from datetime import datetime
from threading import Thread

# Set the recording directory
recording_dir = "/mnt/usb/Haut_Recs/"

def start_gstreamer():
    """Start GStreamer pipeline to mix audio from SRT inputs and files in Haut_Recs2"""
    gst_command = [
        "gst-launch-1.0", "-v",

        # Play MP3 files from Haut_Recs2 folder sequentially using multifilesrc
        "multifilesrc", f"location={recording_dir}audio_chunk_%04d.mp3", "loop=true", "start-index=1",
        "!", "decodebin", "!", "audioconvert", "!", "audioresample",
        "!", "audio/x-raw,format=S16BE,rate=44100,channels=2",
        "!", "queue", "!", "mixer.",

        # SRT Stream 1 (8801)
        "srtsrc", "uri=srt://:8801?mode=listener", "!", "queue",
        "!", "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2",
        "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!", "queue", "!", "mixer.",

        # SRT Stream 2 (8803)
        "srtsrc", "uri=srt://:8803?mode=listener", "!", "queue",
        "!", "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2",
        "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!", "queue", "!", "mixer.",

        # Audio Mixer
        "audiomixer", "name=mixer", "!", "audioconvert", "!", "audioresample",
        "!", "audio/x-raw,format=S16BE,channels=2,rate=44100", "!", "tee", "name=t",

        # Send mixed audio to SRT (8802)
        "t.", "!", "queue", "!", "rtpL16pay", "!", "srtsink", "uri=srt://:8802?mode=listener", "wait-for-connection=false",

        # Send mixed audio to Shoutcast radio
        "t.", "!", "queue", "!", "audioconvert", "!", "audioresample", "!", "lamemp3enc", "bitrate=128",
        "!", "shout2send", "ip=s40.myradiostream.com", "port=23058", "mount=/stream", "password=5e4ThU3VW"
    ]

    print("Starting GStreamer pipeline with SRT streams and MP3 files from Haut_Recs2...")
    return subprocess.Popen(gst_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def record_chunk():
    """Continuously records 1-minute chunks from the mixed audio output."""
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"{recording_dir}audio_chunk_{timestamp}.mp3"

        record_command = [
            "gst-launch-1.0", "-e",

            # Capture the mixed audio output from 8802
            "srtsrc", "uri=srt://127.0.0.1:8802", "!", "queue",
            "!", "application/x-rtp,media=audio,clock-rate=44100,encoding-name=L16,channels=2",
            "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample",

            # Encoding and writing
            "!", "lamemp3enc", "bitrate=192",
            "!", "filesink", f"location={output_file}", "async=false"
        ]

        print(f"Recording: {output_file}")

        try:
            # Start recording in the background
            process = subprocess.Popen(record_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for exactly 60 seconds
            time.sleep(60)

            # Stop the recording process
            process.terminate()
            process.wait()

            print(f"Finished recording: {output_file}")

        except Exception as e:
            print(f"Error during recording: {e}")

if __name__ == "__main__":
    try:
        gst_process = start_gstreamer()  # Start GStreamer pipeline in the background

        # Run recording in a separate thread
        record_thread = Thread(target=record_chunk, daemon=True)
        record_thread.start()

        # Keep the main process running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Stopping processes...")
        gst_process.terminate()
        gst_process.wait()
