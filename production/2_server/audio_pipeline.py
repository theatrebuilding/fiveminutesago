#!/usr/bin/env python3
import os
import sys

# Allow import from parent directory.
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

cfg = load_config()

ports = cfg.get("ports", {})
audio_cfg = cfg.get("audio", {})

audio_send_tn = ports.get("audio_send_tn")
audio_send_dk = ports.get("audio_send_dk")
audio_receive_dk = ports.get("audio_receive_dk")
audio_receive_tn = ports.get("audio_receive_tn")

streaming_settings = cfg.get("streaming_settings_audio", "")

clock_rate = audio_cfg.get("rate", 48000)
channels = audio_cfg.get("channels", 2)
encoding_name = audio_cfg.get("encoding_name", "L16")


def require_config():
    missing = []

    required_values = {
        "ports.audio_send_tn": audio_send_tn,
        "ports.audio_send_dk": audio_send_dk,
        "ports.audio_receive_dk": audio_receive_dk,
        "ports.audio_receive_tn": audio_receive_tn,
        "audio.rate": clock_rate,
        "audio.channels": channels,
        "audio.encoding_name": encoding_name,
    }

    for name, value in required_values.items():
        if value is None or value == "":
            missing.append(name)

    if missing:
        raise RuntimeError("Missing required config values: " + ", ".join(missing))


def srt_listener_uri(port):
    uri = f"srt://:{port}?mode=listener"

    if streaming_settings:
        uri += f"&{streaming_settings}"

    return uri


def build_audio_pipeline():
    require_config()

    rtp_caps = (
        f"application/x-rtp,"
        f"media=audio,"
        f"clock-rate={clock_rate},"
        f"encoding-name={encoding_name},"
        f"channels={channels}"
    )

    pipeline = f"""
        srtsrc name=a_send_tn
          uri="{srt_listener_uri(audio_send_tn)}"
          wait-for-connection=false
          ! queue
          ! {rtp_caps}
          ! tee name=tee_tn

        srtsrc name=a_send_dk
          uri="{srt_listener_uri(audio_send_dk)}"
          wait-for-connection=false
          ! queue
          ! {rtp_caps}
          ! tee name=tee_dk

        tee_tn.
          ! queue
          ! srtsink name=a_recv_dk
              uri="{srt_listener_uri(audio_receive_dk)}"
              wait-for-connection=false

        tee_dk.
          ! queue
          ! srtsink name=a_recv_tn
              uri="{srt_listener_uri(audio_receive_tn)}"
              wait-for-connection=false
    """

    return pipeline.strip()


if __name__ == "__main__":
    print("Audio Pipeline:")
    print(build_audio_pipeline())