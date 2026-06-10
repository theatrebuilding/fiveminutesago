from __future__ import annotations

import unittest

from production.audio_support import (
    alsa_runtime_device,
    build_gst_audio_raw_caps,
    build_input_pair_mix_element,
    build_output_pair_mix_element,
    channel_pairs_for_count,
    choose_audio_hardware_channels,
    normalize_audio_channel_pair,
    resolve_audio_hardware_channels,
)


class AudioRoutingTests(unittest.TestCase):
    def test_channel_pair_validation_accepts_stereo_pairs(self) -> None:
        self.assertEqual(normalize_audio_channel_pair("3/4", "test.pair"), [3, 4])
        self.assertEqual(normalize_audio_channel_pair([5, 6], "test.pair"), [5, 6])

    def test_channel_pair_validation_rejects_non_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "odd channel"):
            normalize_audio_channel_pair([2, 3], "test.pair")
        with self.assertRaisesRegex(ValueError, "consecutive"):
            normalize_audio_channel_pair([1, 3], "test.pair")

    def test_pair_generation_uses_even_stereo_pairs(self) -> None:
        self.assertEqual(
            channel_pairs_for_count(6),
            [
                {"value": "1/2", "label": "Channels 1/2", "channels": [1, 2], "hardware_channels": 2},
                {"value": "3/4", "label": "Channels 3/4", "channels": [3, 4], "hardware_channels": 4},
                {"value": "5/6", "label": "Channels 5/6", "channels": [5, 6], "hardware_channels": 6},
            ],
        )

    def test_pair_generation_uses_full_supported_hardware_layout_for_pair(self) -> None:
        self.assertEqual(choose_audio_hardware_channels([1, 2], [10, 12]), 12)
        self.assertEqual(choose_audio_hardware_channels([3, 4], [2, 10, 12]), 12)
        self.assertEqual(channel_pairs_for_count(6, [2, 6])[0]["hardware_channels"], 6)
        self.assertEqual(channel_pairs_for_count(6, [2, 6])[1]["hardware_channels"], 6)

    def test_supported_counts_override_stale_pair_width(self) -> None:
        self.assertEqual(resolve_audio_hardware_channels(2, [1, 2], [10], "hardware_channels"), 10)
        self.assertEqual(resolve_audio_hardware_channels(4, [3, 4], [2, 12], "hardware_channels"), 12)

    def test_hw_devices_use_plug_layer_for_runtime_compatibility(self) -> None:
        self.assertEqual(alsa_runtime_device("hw:2,0"), "plughw:2,0")
        self.assertEqual(alsa_runtime_device("plughw:2,0"), "plughw:2,0")
        self.assertEqual(alsa_runtime_device("default"), "default")
        self.assertEqual(alsa_runtime_device("hw:bad"), "hw:bad")

    def test_input_pair_matrix_maps_hardware_pair_to_stereo(self) -> None:
        element = build_input_pair_mix_element([3, 4], 6)

        self.assertIn("audiomixmatrix", element)
        self.assertIn("in-channels=6", element)
        self.assertIn("out-channels=2", element)
        self.assertIn("<(double)0.0, (double)0.0, (double)1.0", element)
        self.assertIn("<(double)0.0, (double)0.0, (double)0.0, (double)1.0", element)

    def test_output_pair_matrix_maps_stereo_to_hardware_pair(self) -> None:
        element = build_output_pair_mix_element([5, 6], 8)

        self.assertIn("audiomixmatrix", element)
        self.assertIn("in-channels=2", element)
        self.assertIn("out-channels=8", element)
        self.assertIn("channel-mask=0", element)
        self.assertIn("<(double)1.0, (double)0.0>", element)
        self.assertIn("<(double)0.0, (double)1.0>", element)

    def test_raw_caps_mark_multichannel_hardware_as_unpositioned(self) -> None:
        self.assertEqual(
            build_gst_audio_raw_caps(audio_format="S16LE", channels=10, rate=48000),
            "audio/x-raw,format=S16LE,layout=interleaved,channels=10,rate=48000,channel-mask=(bitmask)0x0",
        )
        self.assertEqual(
            build_gst_audio_raw_caps(audio_format="S16LE", channels=2, rate=48000),
            "audio/x-raw,format=S16LE,layout=interleaved,channels=2,rate=48000",
        )


    def test_default_stereo_pair_needs_no_matrix(self) -> None:
        self.assertEqual(build_input_pair_mix_element([1, 2], 2), "")
        self.assertEqual(build_output_pair_mix_element([1, 2], 2), "")


if __name__ == "__main__":
    unittest.main()
