from __future__ import annotations

from dataclasses import dataclass
import unittest

from control_app.services.sender_recovery import (
    CAPTURE_ONLY_MODE,
    DEGRADED_PHASE,
    NORMAL_PHASE,
    PLAYBACK_DSP_MODE,
    RESTORING_PHASE,
    VIDEO_ONLY_MODE,
    SenderRecoveryPolicy,
)


@dataclass(frozen=True)
class Request:
    role: str = "sender"
    country: str = "tn"
    audio_source: str = "device"
    sender_audio_mode: str = "aec"
    audio_device: str | None = "hw:1,0"
    sender_playback_device: str | None = "hw:0,0"
    video_source: str = "config"
    video_device: str | None = None
    sender_audio_delay_ms: int = 0

    @property
    def audio_enabled(self) -> bool:
        return self.audio_source != "off"


class SenderRecoveryPolicyTests(unittest.TestCase):
    def test_playback_dsp_preflight_failure_starts_capture_only_and_schedules_retry(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()

        active = policy.begin(request, 100.0, ["missing alsasink"])

        self.assertEqual(active.sender_audio_mode, "capture-only")
        snapshot = policy.snapshot(100.0)
        self.assertEqual(snapshot["phase"], DEGRADED_PHASE)
        self.assertEqual(snapshot["desired_mode"], PLAYBACK_DSP_MODE)
        self.assertEqual(snapshot["active_mode"], CAPTURE_ONLY_MODE)
        self.assertEqual(snapshot["next_retry_in_seconds"], 10)

    def test_playback_dsp_early_exit_degrades_to_capture_only(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        policy.begin(request, 100.0)
        policy.launched(request, 100.0)

        action = policy.on_exit(exit_code=1, now=105.0)

        self.assertEqual(action.kind, "launch")
        self.assertEqual(action.request.sender_audio_mode, "capture-only")
        snapshot = policy.snapshot(105.0)
        self.assertEqual(snapshot["phase"], DEGRADED_PHASE)
        self.assertEqual(snapshot["active_mode"], CAPTURE_ONLY_MODE)
        self.assertEqual(snapshot["last_failure"]["uptime_seconds"], 5.0)

    def test_capture_only_failure_degrades_to_video_only(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        active = policy.begin(request, 100.0, ["playback unavailable"])
        policy.launched(active, 100.0)

        action = policy.on_exit(exit_code=1, now=110.0)

        self.assertEqual(action.kind, "launch")
        self.assertEqual(action.request.audio_source, "off")
        snapshot = policy.snapshot(110.0)
        self.assertEqual(snapshot["active_mode"], VIDEO_ONLY_MODE)
        self.assertEqual(snapshot["phase"], DEGRADED_PHASE)

    def test_begin_degraded_can_start_video_only_for_capture_preflight_failure(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        fallback = Request(audio_source="off", sender_audio_mode="capture-only", audio_device=None, sender_playback_device=None)

        active = policy.begin_degraded(request, fallback, 100.0, "Sender capture preflight failed")

        self.assertEqual(active.audio_source, "off")
        snapshot = policy.snapshot(100.0)
        self.assertEqual(snapshot["phase"], DEGRADED_PHASE)
        self.assertEqual(snapshot["desired_mode"], PLAYBACK_DSP_MODE)
        self.assertEqual(snapshot["active_mode"], VIDEO_ONLY_MODE)
        self.assertEqual(snapshot["next_retry_in_seconds"], 10)

    def test_begin_degraded_does_not_schedule_restore_when_desired_capture_only(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request(sender_audio_mode="capture-only", sender_playback_device=None)
        fallback = Request(audio_source="off", sender_audio_mode="capture-only", audio_device=None, sender_playback_device=None)

        policy.begin_degraded(request, fallback, 100.0, "Sender capture preflight failed")

        snapshot = policy.snapshot(100.0)
        self.assertEqual(snapshot["desired_mode"], CAPTURE_ONLY_MODE)
        self.assertEqual(snapshot["active_mode"], VIDEO_ONLY_MODE)
        self.assertIsNone(snapshot["next_retry_at"])

    def test_playback_preview_watchdog_degrades_to_capture_only(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        policy.begin(request, 100.0)
        policy.launched(request, 100.0)

        action = policy.degrade_playback_stall(125.0, "Playback + DSP stopped producing preview frames.")

        self.assertEqual(action.kind, "launch")
        self.assertEqual(action.request.sender_audio_mode, "capture-only")
        snapshot = policy.snapshot(125.0)
        self.assertEqual(snapshot["phase"], DEGRADED_PHASE)
        self.assertEqual(snapshot["active_mode"], CAPTURE_ONLY_MODE)
        self.assertEqual(snapshot["last_failure"]["reason"], "preview_watchdog")

    def test_restore_attempt_clears_degraded_after_stable_window(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        policy.begin(request, 100.0, ["playback unavailable"])

        self.assertTrue(policy.due_for_retry(110.0))
        restore_request = policy.prepare_restore_attempt(110.0)
        self.assertEqual(restore_request, request)
        self.assertEqual(policy.snapshot(110.0)["phase"], RESTORING_PHASE)
        self.assertFalse(policy.mark_stable(139.0))
        self.assertTrue(policy.mark_stable(140.0))
        snapshot = policy.snapshot(140.0)
        self.assertEqual(snapshot["phase"], NORMAL_PHASE)
        self.assertFalse(snapshot["degraded"])
        self.assertEqual(snapshot["retry_count"], 0)

    def test_backoff_caps_at_120_seconds(self) -> None:
        policy = SenderRecoveryPolicy()
        request = Request()
        policy.begin(request, 0.0, ["first failure"])

        for now in (10.0, 40.0, 100.0, 220.0, 340.0):
            policy.defer_retry(now, "still failing")

        self.assertEqual(policy.snapshot(340.0)["next_retry_in_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
