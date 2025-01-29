import gi
import yaml
import sys
from gi.repository import Gst

gi.require_version('Gst', '1.0')
Gst.init(None)

CONFIG_FILE = "config.yaml"

def load_config():
    with open(CONFIG_FILE, "r") as file:
        return yaml.safe_load(file)

def build_pipeline(config):
    node_A_in = config["srt"]["input"]["node_A"]["uri"]
    node_C_in = config["srt"]["input"]["node_C"]["uri"]
    node_B_out = config["srt"]["output"]["node_B"]["uri"]
    node_D_out = config["srt"]["output"]["node_D"]["uri"]

    video_A_fallback = config["fallback"]["video_A"]
    audio_A_fallback = config["fallback"]["audio_A"]
    video_C_fallback = config["fallback"]["video_C"]
    audio_C_fallback = config["fallback"]["audio_C"]

    bitrate = config["encoding"]["video"]["bitrate"]
    key_int_max = config["encoding"]["video"]["key_int_max"]

    pipeline_str = f"""
    input-selector name=video_selector_A
    input-selector name=audio_selector_A
    input-selector name=video_selector_C
    input-selector name=audio_selector_C
    
    srtsrc uri={node_A_in} ! tsdemux name=demuxA 
      demuxA. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_A.sink_0
      demuxA. ! queue ! opusdec ! audioconvert ! audio_selector_A.sink_0

    srtsrc uri={node_C_in} ! tsdemux name=demuxC 
      demuxC. ! queue ! h264parse ! avdec_h264 ! videoconvert ! video_selector_C.sink_0
      demuxC. ! queue ! opusdec ! audioconvert ! audio_selector_C.sink_0

    videotestsrc pattern={video_A_fallback} ! videoconvert ! video/x-raw, format=I420 ! video_selector_A.sink_1
    audiotestsrc wave={audio_A_fallback} ! audioconvert ! audio_selector_A.sink_1

    videotestsrc pattern={video_C_fallback} ! videoconvert ! video/x-raw, format=I420 ! video_selector_C.sink_1
    audiotestsrc wave={audio_C_fallback} ! audioconvert ! audio_selector_C.sink_1

    video_selector_A. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerA
    audio_selector_A. ! opusenc ! muxerA.
    muxerA. ! queue ! srtsink uri={node_B_out}

    video_selector_C. ! videoconvert ! x264enc tune=zerolatency bitrate={bitrate} key-int-max={key_int_max} ! h264parse ! queue ! mpegtsmux name=muxerC
    audio_selector_C. ! opusenc ! muxerC.
    muxerC. ! queue ! srtsink uri={node_D_out}
    """

    return pipeline_str

def run_pipeline():
    config = load_config()
    pipeline_str = build_pipeline(config)

    print(f"Starting GStreamer pipeline:\n{pipeline_str}\n")
    
    pipeline = Gst.parse_launch(pipeline_str)

    pipeline.set_state(Gst.State.PLAYING)

    try:
        bus = pipeline.get_bus()
        msg = None
        while msg != Gst.MessageType.EOS:
            msg = bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg:
                print(f"GStreamer Message: {msg.type}")
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    run_pipeline()
