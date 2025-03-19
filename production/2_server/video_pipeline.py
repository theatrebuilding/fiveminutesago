"""
Put comments here
"""

def build_video_pipeline():
    return """
        srtsrc uri="srt://:7702?mode=listener"
            ! queue max-size-time=200000000
            ! application/x-rtp,media=video,encoding-name=H264
            ! rtph264depay
            ! avdec_h264
            ! videoconvert
            ! autovideosink
    """.strip()

