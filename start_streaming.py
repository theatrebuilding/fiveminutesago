import subprocess
import time
import threading
import os
from loadEnv import load_env



def main():
    total_lines_printed = print_welcome_message()
    run_gstream()



def print_welcome_message():
    os.system('clear')
    total_lines_printed = 0
    ascii_art_file = 'fiveminutesago.txt'
    if os.path.exists(ascii_art_file):
        with open(ascii_art_file, 'r') as f:
            ascii_art = f.read()
        print(ascii_art)
        total_lines_printed += ascii_art.count('\n') + 2
    else:
        print("ASCII art file not found.")
        total_lines_printed += 1
    return total_lines_printed



def gstreamer_receiver():
    print("Starting gstreamer receiver...")
    
    receiver_pipeline = (
        "gst-launch-1.0 "
        "tcpserversrc port=8000 ! queue ! "
        "application/x-rtp,media=video,encoding-name=H264,payload=96 "
        "! rtph264depay ! tee name=t "
        "t. ! queue ! rtph264pay ! tcpserversink port=9000 recover-policy=keyframe "
        "t. ! queue ! rtph264pay ! tcpserversink port=9001 recover-policy=keyframe"
    )

#    receiver_pipeline = (
#        "gst-launch-1.0 "
#        "tcpserversrc port=8000 ! queue ! "
#        "application/x-rtp,media=video,encoding-name=H264,payload=96 ! "
#        "rtph264depay ! avdec_h264 ! videoconvert ! autovideosink"
#    )


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

def run_gstream():
    create_listener()

def create_listener():
    path_to_env = "/home/theatrebuilding/env.json"
    env = load_env(path_to_env)
    authtoken1 = env.get("PINGGY_TOKEN_ONE")
    authtoken2 = env.get("PINGGY_TOKEN_TWO")
    authtoken3 = env.get("PINGGY_TOKEN_THREE")

    if not authtoken1 or not authtoken2 or not authtoken3:
        print("No Pinggy auth token found. Exiting.")
        return

    threading.Thread(target=gstreamer_receiver, daemon=False).start()

    # Now start pinggy tunnels
    ports = [8000, 9000, 9001]
    tokens = [authtoken1, authtoken2, authtoken3]

    for token, port in zip(tokens, ports):
        run_pinggy_tunnel(token, port)

    print(f"Ingress established with Pinggy using tokens {authtoken1}, {authtoken2}, and {authtoken3}")

    # Keep the listener alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Closing listener")




if __name__ == "__main__":
    main()
