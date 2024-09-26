import os
import subprocess
from datetime import datetime
from threading import Thread
import time

def record_and_chunk(stream_url, output_dir, chunk_duration=3600):
    timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M')
    output_pattern = os.path.join(output_dir, f'fiveminutesago_{timestamp}_%03d.mp3')

    # Command to record the stream and split it into chunks
    ffmpeg_record_cmd = [
        'ffmpeg', '-i', stream_url, '-f', 'segment',
        '-segment_time', str(chunk_duration), '-reset_timestamps', '1',
        output_pattern
    ]

    try:
        # Start recording and chunking
        subprocess.run(ffmpeg_record_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during recording: {e}")

def play_files(output_dir):
    # enable consume and random mode
    subprocess.run(['mpc', 'consume', 'on'])
    subprocess.run(['mpc', 'random', 'on'])

    while True:
        # Get list of all mp3 files in the output directory
        files = [f for f in os.listdir(output_dir) if f.endswith('.mp3')]

        if files:
            # Add all files to the MPC playlist
            for file in files:
                try:
                    subprocess.run(['mpc', 'add', file], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error adding file to playlist: {e}")

            # Play the playlist
            subprocess.run(['mpc', 'play'])
            subprocess.run(['mpc', 'volume', '80'])  # Set volume to 80%

            # Wait until all files in the playlist have been played
            while True:
                try:
                    status = subprocess.check_output(['mpc', 'status']).decode()
                except subprocess.CalledProcessError as e:
                    print(f"Error retrieving status: {e}")
                    break

                # Check if playback has finished
                if 'volume' in status and 'playing' not in status and 'paused' not in status:
                    break

                time.sleep(5)

            # Clear the playlist and reset for the next cycle
            subprocess.run(['mpc', 'clear'])
        else:
            # Sleep briefly before checking for new files
            time.sleep(5)

def main():
    stream_url = "http://s40.myradiostream.com:23058/stream"  # Replace with Streaming URL
    output_dir = "/mnt/usb/"  # Replace with output directory

    # Ensure the output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Start the playback thread
    playback_thread = Thread(target=play_files, args=(output_dir,))
    playback_thread.daemon = True
    playback_thread.start()

    # Start the recording and chunking process
    try:
        while True:
            record_and_chunk(stream_url, output_dir)
    except KeyboardInterrupt:
        print("Recording stopped.")

if __name__ == "__main__":
    main()