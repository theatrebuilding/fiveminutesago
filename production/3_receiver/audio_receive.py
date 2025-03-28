import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import os
import sys

# Insert parent directory for config_loader
script_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config_loader import load_config

class AudioReceiver:
    def __init__(self, country, device):
        self.country = country
        self.device = device
        self.pipeline = None
        self.loop = None

    def build_pipeline(self):
        config = load_config()
        server_address = config.get("server_ip", "127.0.0.1")

        # Choose the audio receive port based on the country
        if self.country.lower() == "tn":
            receive_port = config.get("ports", {}).get("audio_receive_tn")
        else:
            receive_port = config.get("ports", {}).get("audio_receive_dk")

        pipeline_str = f"""
            srtsrc uri="srt://{server_address}:{receive_port}?mode=caller&latency=100"
                ! queue max-size-time=200000000
                ! application/x-rtp,media=audio,clock-rate=32000,encoding-name=L16,channels=2
                ! rtpL16depay
                ! audioconvert
                ! audioresample
                ! alsasink device="{self.device}"
        """
        return pipeline_str.strip()

    def on_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("AudioReceiver: End of Stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"AudioReceiver: ERROR -> {err}")
            if debug:
                print(f"Debug info: {debug}")
            self.stop()

    def run(self):
        pipeline_str = self.build_pipeline()
        print("AudioReceiver: Pipeline:", pipeline_str)

        self.pipeline = Gst.parse_launch(pipeline_str)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop = GLib.MainLoop()
        try:
            self.loop.run()
        except Exception as e:
            print(f"AudioReceiver: Exception -> {e}")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("AudioReceiver: Pipeline stopped.")

    def stop(self):
        if self.loop:
            self.loop.quit()
