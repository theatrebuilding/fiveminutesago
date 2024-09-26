import subprocess
import time
import sys
import threading
import socket
import os
import json

# Function to run command without waiting for it to complete.
def run_command(command):
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        # Read and print the output in a separate thread
        threading.Thread(target=read_process_output, args=(process,)).start()
        return process
    except Exception as e:
        print(f"Failed to run command: {' '.join(command)}\nError: {e}")
        return None

# Function to read and print the output of a subprocess
def read_process_output(process):
    for line in process.stdout:
        print(line, end='')

def check_stream(stream_url):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", stream_url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error checking stream {stream_url}: {e}")
        return False

# Continuously check for the availability of streams and update the available_streams list.
def monitor_streams(LOCAL_IP, PORT, STREAM_NAMES, available_streams, lock):
    while True:
        for stream in STREAM_NAMES:
            STREAM_URL = f"http://{LOCAL_IP}:{PORT}/{stream}"
            try:
                is_available = check_stream(STREAM_URL)
                with lock:
                    if is_available and STREAM_URL not in available_streams:
                        available_streams.append(STREAM_URL)
                    elif not is_available and STREAM_URL in available_streams:
                        available_streams.remove(STREAM_URL)
            except Exception as e:
                with lock:
                    print(f"Exception in monitor_streams for {STREAM_URL}: {e}")
        time.sleep(5)

# Retrieves the local IP address of the machine.
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        LOCAL_IP = s.getsockname()[0]
    except Exception:
        LOCAL_IP = '127.0.0.1'
    finally:
        s.close()
    return LOCAL_IP

# Builds the ffmpeg command to merge and stream whatever streams are currently available
def build_ffmpeg_command(streams, radio_stream_output_url):
    if not streams:
        return None

    cmd = ["ffmpeg", "-loglevel", "error"]

    for i, stream in enumerate(streams):
        cmd.extend([
            "-thread_queue_size", "1024",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "2",
            "-i", stream
        ])

    filter_complex_parts = []
    for i in range(len(streams)):
        # Resample each input to a common sample rate and format
        filter_complex_parts.append(
            f"[{i}:a]aresample=44100,asetrate=44100,aresample=async=1[a{i}];"
        )
    # Mix the inputs together
    inputs = ''.join([f"[a{i}]" for i in range(len(streams))])
    filter_complex_parts.append(
        f"{inputs}amix=inputs={len(streams)}[a]"
    )

    filter_complex = ''.join(filter_complex_parts)

    # print(f"Filter complex: {filter_complex}")

    # Send to myradiostream
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[a]",
        "-f", "mp3",
        radio_stream_output_url
    ])

    return cmd

def main():
    # Clear the terminal
    os.system('clear')

    # Initialize total lines printed
    total_lines_printed = 0

    # Read and display ASCII art from the text file
    ascii_art_file = 'fiveminutesago.txt'  # Using the specified ASCII art file
    if os.path.exists(ascii_art_file):
        with open(ascii_art_file, 'r') as f:
            ascii_art = f.read()
        print(ascii_art)
        ascii_art_lines = ascii_art.count('\n') + 2  # +1 to account for the last line
        total_lines_printed += ascii_art_lines
    else:
        print("ASCII art file not found.")
        ascii_art_lines = 1
        total_lines_printed += 1

    # Load configuration from config.json
    config_file = 'config.json'
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config = json.load(f)
        PORT = config.get('port', 8000)  # Default to 8000 if not specified
        STREAM_NAMES = config.get('stream_names', [])
    else:
        print("Configuration file config.json not found. Exiting.")
        return

    # Display the configuration
    print(f"Using port: {PORT}")
    print(f"Monitoring streams: {', '.join(STREAM_NAMES)}")
    total_lines_printed += 2  # For the two lines printed above

    # Reserve space for stream statuses
    num_status_lines = len(STREAM_NAMES)
    print("\n" * num_status_lines)  # Reserve lines for stream statuses
    total_lines_printed += num_status_lines  # Account for the reserved lines

    # Calculate the line number where statuses start
    status_start_line = total_lines_printed - num_status_lines + 1  # +1 because line numbers start at 1

    # External radio stream output URL
    radio_stream_output_url = "icecast://source:5e4ThU3VW@s40.myradiostream.com:23058/stream"

    # List of available streams
    available_streams = []
    lock = threading.Lock()

    # Start a background thread to monitor the streams
    monitor_thread = threading.Thread(target=monitor_streams, args=(get_local_ip(), PORT, STREAM_NAMES, available_streams, lock))
    monitor_thread.daemon = True
    monitor_thread.start()

    ffmpeg_process = None
    previous_streams = []

    while True:
        with lock:
            streams = list(available_streams)

        # Move the cursor to the line where statuses start
        sys.stdout.write(f"\033[{status_start_line};0H")  # Move cursor to line status_start_line, column 0
        sys.stdout.flush()

        # Display the status of each stream
        for stream_name in STREAM_NAMES:
            stream_url = f"http://{get_local_ip()}:{PORT}/{stream_name}"
            # Clear the line before writing
            sys.stdout.write('\033[K')
            if stream_url in streams:
                # Available - print in green
                print(f"\033[32m{stream_name}: Available\033[0m")
            else:
                # Not available - print in red
                print(f"\033[31m{stream_name}: Not Available\033[0m")

        # After printing statuses, move the cursor to the line after the statuses
        output_line = total_lines_printed + 2  # Line after the statuses
        sys.stdout.write(f"\033[{output_line};0H")
        sys.stdout.flush()

        # Check for changes in the stream list
        if set(streams) != set(previous_streams):
            if ffmpeg_process:
                print("Stream list changed. Restarting FFmpeg process.")
                ffmpeg_process.terminate()
                ffmpeg_process.wait()
                ffmpeg_process = None

            ffmpeg_cmd = build_ffmpeg_command(streams, radio_stream_output_url)
            if ffmpeg_cmd:
                print("Starting FFmpeg process with updated streams.")
                print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
                ffmpeg_process = run_command(ffmpeg_cmd)
            else:
                print("No streams available to start FFmpeg process.")

            # Update the previous_streams list
            previous_streams = streams.copy()
        else:
            # No change in streams; do nothing
            pass

        # Wait before checking again
        time.sleep(5)

if __name__ == "__main__":
    main()
