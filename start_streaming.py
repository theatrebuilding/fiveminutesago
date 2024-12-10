import subprocess
import time
import sys
import threading
import socket
import os
import json
import ngrok
from saveNgrokUrl import update_ngrok_url
from loadEnv import load_env

def gstreamer_receiver():
    # Start the receiver pipeline
    print("Starting gstreamer receiver...")
    
    receiver_pipeline = (
        f"gst-launch-1.0 "
        f"fdsrc fd=1 ! tcpserversink port=8000"
    )

    os.system(receiver_pipeline)


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
def monitor_streams(LOCAL_IP, clients, available_streams, lock):
    while True:
        for client in clients:
            STREAM_URL = f"http://{LOCAL_IP}:{client.port}/{client.name}"
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


class Client:
    port = 0
    name = ""

    def __init__(self, port, name):
        self.port = port
        self.name = name


def load_config(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except:
        print("Configuration file config.json not found. Exiting.")
    else:
        clients = []
        port = config.get('port', 8000)  # Default to 8000 if not specified
        stream_names = config.get('stream_names', [])
        for name in stream_names:
            clients.append(Client(port, name))
        return clients


def main():
    total_lines_printed = print_welcome_message()

    gstream = True

    # Load configuration from config.json
    clients = load_config('config.json')

    # Display the configuration
    total_lines_printed = display_configuration(clients, total_lines_printed)

    if gstream:
        run_gstream(clients, total_lines_printed)
    else:
        monitor_stream_statuses(clients, total_lines_printed)


def run_gstream(clients, total_lines_printed):
    create_listener()



def create_listener():
    # Create ngrok session and update the ngrok url
    pathToEnv = "/home/theatrebuilding/env.json"
    env = load_env(pathToEnv)
    authtoken = env.get("NGROK_AUTH_TOKEN")
    if not authtoken:
        print("NGROK_AUTH_TOKEN not found in env.json. Exiting.")
        return
    ngrok.set_auth_token(authtoken)
    listener = ngrok.forward(8000, "tcp")

    # Output ngrok url to console
    print(f"Ingress established at {listener.url()}")

    ngrok_url = listener.url() 
    update_ngrok_url(ngrok_url, env_path=pathToEnv)
    # gstreamer_receiver()

    # Keep the listener alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Closing listener")



def print_welcome_message():
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
    return total_lines_printed


def display_configuration(clients, total_lines_printed):
    print(f"Using port: {clients[0].port}")
    stream_list = f"Monitoring streams:"
    for client in clients:
        stream_list.join([", " + client.name])
    print(stream_list)
    total_lines_printed += 2  # For the two lines printed above
    return total_lines_printed


def monitor_stream_statuses(clients, total_lines_printed):
    # Reserve space for stream statuses
    num_status_lines = len(clients)
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
    monitor_thread = threading.Thread(target=monitor_streams,
                                      args=(get_local_ip(), clients, available_streams, lock))
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
        for client in clients:
            stream_url = f"http://{get_local_ip()}:{client.port}/{client.name}"
            # Clear the line before writing
            sys.stdout.write('\033[K')
            if stream_url in streams:
                # Available - print in green
                print(f"\033[32m{client.name}: Available\033[0m")
            else:
                # Not available - print in red
                print(f"\033[31m{client.name}: Not Available\033[0m")

        # After printing statuses, move the cursor to the line after the statuses
        output_line = total_lines_printed + 2  # Line after the statuses
        sys.stdout.write(f"\033[{output_line};0H")
        sys.stdout.flush()

        # Check for changes in the stream list
        if ffmpeg_process and set(streams) != set(previous_streams):
            print("Stream list changed. Restarting FFmpeg process.")
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
            ffmpeg_process = None

        ffmpeg_cmd = build_ffmpeg_command(streams, radio_stream_output_url)
        if ffmpeg_cmd and set(streams) != set(previous_streams):
            print("Starting FFmpeg process with updated streams.")
            print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
            ffmpeg_process = run_command(ffmpeg_cmd)
        else:
            print("No streams available to start FFmpeg process.")

        # Update the previous_streams list
        previous_streams = streams.copy()

        # Wait before checking again
        time.sleep(5)


if __name__ == "__main__":
    main()
