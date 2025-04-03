#!/usr/bin/env python3
import os
import sys

# 1) Insert parent directory into Python path so we can import config_loader.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 2) Import the configuration loader and load config.
from config_loader import load_config
cfg = load_config()

# 3) Fetch port values and streaming settings from the config.
audio_send_tn       = cfg.get("ports", {}).get("audio_send_tn")
audio_send_dk       = cfg.get("ports", {}).get("audio_send_dk")
audio_receive_dk    = cfg.get("ports", {}).get("audio_receive_dk")
audio_receive_tn    = cfg.get("ports", {}).get("audio_receive_tn")

streaming_settings  = cfg.get("streaming_settings_audio", "")
clock_rate          = cfg.get("audio", {}).get("rate", 32000)
channels            = cfg.get("audio", {}).get("channels", 2)
encoding_name       = cfg.get("audio", {}).get("encoding_name", "L16")
audio_format        = cfg.get("audio", {}).get("format", "S16BE") 

compression_level   = cfg.get("webrtcdsp_settings", {}).get("compression-gain-db", 0)
delay_agnostic      = cfg.get("webrtcdsp_settings", {}).get("delay-agnostic", True)
echo_cancel         = cfg.get("webrtcdsp_settings", {}).get("echo-cancel", True)
echo_suppression  = cfg.get("webrtcdsp_settings", {}).get("echo-suppression-level", "high")
extended_filter = cfg.get("webrtcdsp_settings", {}).get("extended-filter", True)
experimental_agc = cfg.get("webrtcdsp_settings", {}).get("experimental-agc", False)
gain_control = cfg.get("webrtcdsp_settings", {}).get("gain-control", False)
gain_control_mode = cfg.get("webrtcdsp_settings", {}).get("gain-control-mode", "adaptive-digital")
high_pass_filter = cfg.get("webrtcdsp_settings", {}).get("high-pass-filter", False)
limiter = cfg.get("webrtcdsp_settings", {}).get("limiter", True)
noise_suppression = cfg.get("webrtcdsp_settings", {}).get("noise-suppression", False)
noise_suppression_level = cfg.get("webrtcdsp_settings", {}).get("noise-suppression-level", "low")
startup_min_volume = cfg.get("webrtcdsp_settings", {}).get("startup-min-volume", 12)
target_level_dbfs = cfg.get("webrtcdsp_settings", {}).get("target-level-dbfs", 3)
voice_detection = cfg.get("webrtcdsp_settings", {}).get("voice-detection", False)
voice_detection_fs = cfg.get("webrtcdsp_settings", {}).get("voice-detection-frame-size-ms", 0)
voice_detection_likelihood = cfg.get("webrtcdsp_settings", {}).get("voice-detection-likelihood", "low")

def build_audio_pipeline():
    pipeline = f"""
        srtsrc name=a_send_tn uri=srt://:{audio_send_tn}?mode=listener !
          queue !
          application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          audioconvert !
          audioresample !
          audio/x-raw,format=S16LE,channels={channels},rate={clock_rate} !
          tee name=tee_tn

        srtsrc name=a_send_dk uri=srt://:{audio_send_dk}?mode=listener !
          queue !
          application/x-rtp,media=audio,clock-rate={clock_rate},encoding-name={encoding_name},channels={channels} !
          rtpL16depay !
          audioconvert !
          audioresample !
          audio/x-raw,format=S16LE,channels={channels},rate={clock_rate} !
          tee name=tee_dk

        tee_tn. ! queue !
          webrtcechoprobe name=probe_tn ! fakesink async=false

        tee_dk. ! queue !
          webrtcechoprobe name=probe_dk ! fakesink async=false

        tee_tn. ! queue ! 
          webrtcdsp probe=probe_dk compression-gain-db={compression_level} delay-agnostic={delay_agnostic} echo-cancel={echo_cancel} echo-suppression-level={echo_suppression} experimental-agc={experimental_agc} extended-filter={extended_filter} gain-control={gain_control} gain-control-mode={gain_control_mode} high-pass-filter={high_pass_filter} limiter={limiter} noise-suppression={noise_suppression} noise-suppression-level={noise_suppression_level} startup-min-volume={startup_min_volume} target-level-dbfs={target_level_dbfs} !
          audioconvert ! audioresample !
          audio/x-raw,format={audio_format},channels={channels},rate={clock_rate} !
          rtpL16pay !
          srtsink name=a_recv_dk uri=srt://:{audio_receive_dk}?mode=listener

        tee_dk. ! queue !
          webrtcdsp probe=probe_tn compression-gain-db={compression_level} delay-agnostic={delay_agnostic} echo-cancel={echo_cancel} echo-suppression-level={echo_suppression} experimental-agc={experimental_agc} extended-filter={extended_filter} gain-control={gain_control} gain-control-mode={gain_control_mode} high-pass-filter={high_pass_filter} limiter={limiter} noise-suppression={noise_suppression} noise-suppression-level={noise_suppression_level} startup-min-volume={startup_min_volume} target-level-dbfs={target_level_dbfs} !
          audioconvert ! audioresample !
          audio/x-raw,format={audio_format},channels={channels},rate={clock_rate} !
          rtpL16pay !
          srtsink name=a_recv_tn uri=srt://:{audio_receive_tn}?mode=listener

    """
    return pipeline.strip()


if __name__ == "__main__":
    print("Audio Pipeline:")
    print(build_audio_pipeline())
