"""
Put comments here
"""

def build_audio_pipeline(server_address="localhost", receive_port=8802):
    return f"""
        srtsrc uri="srt://{server_address}:{receive_port}?mode=caller&latency=1000&maxbw=0"
            ! queue max-size-time=200000000
            ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! alsasink device=hw:2,0
    """.strip()
