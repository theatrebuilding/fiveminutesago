from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda _file: {})

if "gi" not in sys.modules:
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args, **_kwargs: None
    repository = types.ModuleType("gi.repository")

    class _FakeGst:
        Pad = object
        Pipeline = object
        Element = object

        @staticmethod
        def init(_value=None):
            return None

    repository.Gst = _FakeGst
    repository.GLib = types.SimpleNamespace()
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository

from control_app.services.runtime_service import RuntimeLaunchRequest, RuntimeService


class RuntimeGstPreflightTests(unittest.TestCase):
    def test_playback_preflight_passes_caps_as_single_argv_token(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="device",
            sender_audio_mode="aec",
            sender_playback_output_channels=(1, 2),
            sender_playback_hardware_channels=2,
        )

        with (
            patch("control_app.services.runtime_service.shutil.which", return_value="/usr/bin/gst-launch-1.0"),
            patch("control_app.services.runtime_service.subprocess.run", return_value=_run_result()) as run,
        ):
            error = service._gst_playback_open_error(request, "hw:3,0", 48000)

        self.assertIsNone(error)
        command = run.call_args.args[0]
        self.assertIn("capsfilter", command)
        self.assertIn("caps=audio/x-raw,channels=2,rate=48000", command)
        self.assertNotIn("audio", command)
        self.assertIn("device=hw:3,0", command)

    def test_multichannel_playback_preflight_keeps_mix_matrix_as_one_property(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="device",
            sender_audio_mode="aec",
            sender_playback_output_channels=(5, 6),
            sender_playback_hardware_channels=10,
        )

        with (
            patch("control_app.services.runtime_service.shutil.which", return_value="/usr/bin/gst-launch-1.0"),
            patch("control_app.services.runtime_service.subprocess.run", return_value=_run_result()) as run,
        ):
            error = service._gst_playback_open_error(request, "hw:3,0", 48000)

        self.assertIsNone(error)
        command = run.call_args.args[0]
        self.assertIn("audiomixmatrix", command)
        matrix_args = [arg for arg in command if arg.startswith("matrix=")]
        self.assertEqual(len(matrix_args), 1)
        self.assertIn("<(double)1.0, (double)0.0>", matrix_args[0])
        self.assertIn("caps=audio/x-raw,channels=10,rate=48000", command)

    def test_preflight_failure_includes_exact_command_for_diagnostics(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="device",
            sender_audio_mode="aec",
        )

        with (
            patch("control_app.services.runtime_service.shutil.which", return_value="/usr/bin/gst-launch-1.0"),
            patch(
                "control_app.services.runtime_service.subprocess.run",
                return_value=_run_result(returncode=1, stderr='WARNING: erroneous pipeline: no element "audio"'),
            ),
        ):
            error = service._gst_playback_open_error(request, "hw:3,0", 48000)

        assert error is not None
        self.assertIn('WARNING: erroneous pipeline: no element "audio"', error)
        self.assertIn("[command: gst-launch-1.0", error)
        self.assertIn("capsfilter caps=audio/x-raw,channels=2,rate=48000", error)
        self.assertIn(" ! ", error)
        self.assertNotIn("'!'", error)
        self.assertIn("device=hw:3,0", error)

    def test_restore_preflight_can_skip_capture_open_when_fallback_owns_mic(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="device",
            sender_audio_mode="aec",
            audio_device="hw:3,0",
            sender_playback_device="hw:3,0",
            sender_audio_rate=48000,
        )

        with (
            patch.object(service, "_gst_element_available", return_value=True),
            patch.object(service, "_alsa_device_error", return_value=None),
            patch.object(service, "_gst_capture_open_error", return_value="capture preflight failed: device busy") as capture_open,
            patch.object(service, "_gst_playback_open_error", return_value=None),
        ):
            errors = service._sender_preflight_errors(request, skip_capture_open=True)

        self.assertEqual(errors, [])
        capture_open.assert_not_called()

    def test_restore_preflight_reports_capture_open_when_not_skipped(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="device",
            sender_audio_mode="aec",
            audio_device="hw:3,0",
            sender_playback_device="hw:3,0",
            sender_audio_rate=48000,
        )

        with (
            patch.object(service, "_gst_element_available", return_value=True),
            patch.object(service, "_alsa_device_error", return_value=None),
            patch.object(service, "_gst_capture_open_error", return_value="capture preflight failed: device busy"),
            patch.object(service, "_gst_playback_open_error", return_value=None),
        ):
            errors = service._sender_preflight_errors(request)

        self.assertEqual(errors, ["capture preflight failed: device busy"])

    def test_sender_preflight_requires_rtp_jitterbuffer_for_playback_dsp(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="test",
            sender_audio_mode="aec",
        )

        with (
            patch.object(service, "_gst_element_available", side_effect=lambda element: element != "rtpjitterbuffer"),
            patch.object(service, "_alsa_device_error", return_value=None),
            patch.object(service, "_gst_playback_open_error", return_value=None),
        ):
            errors = service._sender_preflight_errors(request)

        self.assertIn("missing GStreamer element rtpjitterbuffer", errors)

    def test_playback_only_preflight_does_not_require_webrtc_elements(self) -> None:
        service = _runtime_service()
        request = RuntimeLaunchRequest(
            role="sender",
            country="tn",
            audio_source="test",
            sender_audio_mode="playback-only",
        )

        def element_available(element: str) -> bool:
            return element not in {"webrtcdsp", "webrtcechoprobe"}

        with (
            patch.object(service, "_gst_element_available", side_effect=element_available),
            patch.object(service, "_alsa_device_error", return_value=None),
            patch.object(service, "_gst_playback_open_error", return_value=None),
        ):
            errors = service._sender_preflight_errors(request)

        self.assertEqual(errors, [])


def _runtime_service() -> RuntimeService:
    return RuntimeService(
        python_executable=sys.executable,
        project_root=Path("/app"),
        config_path=Path("/config/config.yaml"),
        recording_dir=Path("/mnt/tbdrive"),
        archive_dir=Path("/mnt/tbdrive/video"),
        preview_dir=Path("/mnt/tbdrive/previews"),
        runtime_dir=Path("/mnt/tbdrive/runtime"),
    )


def _run_result(returncode: int = 0, stderr: str = "", stdout: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(returncode=returncode, stderr=stderr, stdout=stdout)


if __name__ == "__main__":
    unittest.main()
