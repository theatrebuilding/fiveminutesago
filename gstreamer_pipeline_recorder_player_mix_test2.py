import subprocess
import time
import os
from datetime import datetime
from threading import Thread

# Set the recording directory
recording_dir = "/mnt/usb/Haut_Recs/"

# GStreamer pipeline command for live streaming
gst_command = [
    "gst-launch-1.0", "-v",
    "srtsrc", "uri=srt://:8801?mode=listener", "!", "queue",
    "!", "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2",
    "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!", "queue", "!", "mixer.",
    
    "srtsrc", "uri=srt://:8803?mode=listener", "!", "queue",
    "!", "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2",
    "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample", "!", "queue", "!", "mixer.",
    
    "audiomixer", "name=mixer", "!", "audioconvert", "!", "audioresample",
    "!", "audio/x-raw,format=S16BE,channels=2,rate=32000", "!", "tee", "name=t",
    
    "t.", "!", "queue", "!", "rtpL16pay", "!", "srtsink", "uri=srt://:8802?mode=listener", "wait-for-connection=false",
    
    "t.", "!", "queue", "!", "audioconvert", "!", "audioresample", "!", "lamemp3enc", "bitrate=128",
    "!", "shout2send", "ip=s40.myradiostream.com", "port=23058", "mount=/stream", "password=5e4ThU3VW"
]

def start_gstreamer():
    """Start the GStreamer pipeline in the background."""
    print("Starting GStreamer pipeline...")
    return subprocess.Popen(gst_command)

def record_chunk():
    """Continuously records 1-minute audio chunks directly from GStreamer."""
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"{recording_dir}audio_chunk_{timestamp}.mp3"

        # GStreamer command to record audio directly into MP3
        record_command = [
            "gst-launch-1.0", "-e",
            "srtsrc", "uri=srt://127.0.0.1:8802", "!", "queue",
            "!", "application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2",
            "!", "rtpL16depay", "!", "audioconvert", "!", "audioresample",
            "!", "lamemp3enc", "bitrate=192", "!", "filesink", f"location={output_file}"
        ]

        print(f"Recording: {output_file}")
        subprocess.run(record_command)  # Run the GStreamer recording process
        time.sleep(1)  # Small delay before next recording

def get_sorted_audio_files():
    """Retrieve all MP3 files in chronological order."""
    files = [f for f in os.listdir(recording_dir) if f.endswith(".mp3")]
    files.sort()  # Sort alphabetically (works with timestamped filenames)
    return [os.path.join(recording_dir, f) for f in files]

def playback_loop():
    """Continuously plays recorded files into the stream on 8802."""
    while True:
        audio_files = get_sorted_audio_files()

        if not audio_files:
            print("No audio files found. Waiting...")
            time.sleep(5)
            continue

        for audio_file in audio_files:
            print(f"Playing {audio_file} into stream...")
            play_command = [
                "gst-launch-1.0", "filesrc", f"location={audio_file}",
                "!", "decodebin", "!", "audioconvert", "!", "audioresample",
                "!", "audio/x-raw,format=S16BE,channels=2,rate=32000",
                "!", "rtpL16pay", "!", "srtsink", "uri=srt://127.0.0.1:8802"
            ]

            subprocess.run(play_command)
            time.sleep(1)  # Small delay before playing next file

if __name__ == "__main__":
    try:
        gst_process = start_gstreamer()  # Start GStreamer in the background

        # Run recording and playback in parallel
        record_thread = Thread(target=record_chunk, daemon=True)
        playback_thread = Thread(target=playback_loop, daemon=True)

        record_thread.start()
        playback_thread.start()

        # Keep the main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Stopping processes...")
        gst_process.terminate()
