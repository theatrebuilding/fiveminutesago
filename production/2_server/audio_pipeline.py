"""
Put comments here
"""

def build_audio_pipeline():
    return """
        srtsrc uri=srt://:8801?mode=listener
            ! queue
            ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! queue
            ! mixer.

        srtsrc uri=srt://:8803?mode=listener
            ! queue
            ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2
            ! rtpL16depay
            ! audioconvert
            ! audioresample
            ! queue
            ! mixer.

        audiomixer name=mixer
            ! audioconvert
            ! audioresample
            ! audio/x-raw,format=S16BE,channels=2,rate=32000
            ! tee name=t

        t. ! queue
            ! rtpL16pay
            ! srtsink uri=srt://:8802?mode=listener wait-for-connection=false

        t. ! queue
            ! audioconvert
            ! audioresample
            ! lamemp3enc bitrate=128
            ! shout2send
                ip=s40.myradiostream.com
                port=23058
                mount=/stream
                password=5e4ThU3VW
    """.strip()
