import subprocess
import time
import sys
import threading
import socket
import os
import json
from loadEnv import load_env



def main():
    total_lines_printed = print_welcome_message()

    run_gstream(clients, total_lines_printed)



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



def gstreamer_receiver():
    # Start the receiver pipeline
    print("Starting gstreamer receiver...")
    
    receiver_pipeline = (
        f"gst-launch-1.0 "
        f"tcpserversrc host=0.0.0.0 port=8000 ! queue ! "
        f"application/x-rtp,media=video,encoding-name=H264,payload=96 "
        f"! rtph264depay ! tee name=t "
        f"t. ! queue ! rtph264pay ! tcpserversink host=0.0.0.0 port=9000 recover-policy=keyframe "
        f"t. ! queue ! rtph264pay ! tcpserversink host=0.0.0.0 port=9001 recover-policy=keyframe"
    )

    os.system(receiver_pipeline)


def run_pinggy_tunnel(token, port):
    command = [
        "../pinggy",
        "-p", "443",
        f"-R0:localhost:{port}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        f"{token}+tcp@a.pinggy.io"
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    threading.Thread(target=print_subprocess_output, args=(process,)).start()

    return process



def print_subprocess_output(process):
    for line in process.stdout:
        print(line, end='')





def run_gstream(clients, total_lines_printed):
    create_listener()



def create_listener():
    pathToEnv = "/home/theatrebuilding/env.json"
    env = load_env(pathToEnv)
    authtoken1 = env.get("PINGGY_TOKEN_ONE")
    authtoken2 = env.get("PINGGY_TOKEN_TWO")
    authtoken3 = env.get("PINGGY_TOKEN_THREE")

    if not authtoken1 or not authtoken2 or not authtoken3:
        print("No Pinggy auth token found. Exiting.")
        return

    # Start GStreamer first
    # If gstreamer_receiver blocks, consider running it in a thread
    # Or start it in background with subprocess if needed
    threading.Thread(target=gstreamer_receiver, daemon=False).start()

    # Now start pinggy tunnels
    port1 = 8000
    port2 = 9000
    port3 = 9001

    run_pinggy_tunnel(authtoken1, port1)
    run_pinggy_tunnel(authtoken2, port2)
    run_pinggy_tunnel(authtoken3, port3)

    print(f"Ingress established with Pinggy using tokens {authtoken1}, {authtoken2}, and {authtoken3}")

    # Keep the listener alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Closing listener")



if __name__ == "__main__":
    main()
