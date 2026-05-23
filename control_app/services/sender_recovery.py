from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


PLAYBACK_DSP_MODE = "playback-dsp"
CAPTURE_ONLY_MODE = "capture-only"
VIDEO_ONLY_MODE = "video-only"

NORMAL_PHASE = "normal"
DEGRADED_PHASE = "degraded"
RESTORING_PHASE = "restoring"
STOPPED_PHASE = "stopped"

HEALTHY_UPTIME_SECONDS = 30.0
RETRY_BACKOFF_SECONDS = (10.0, 30.0, 60.0, 120.0)


@dataclass(frozen=True)
class RecoveryAction:
    kind: str
    request: Any | None = None
    reason: str | None = None


@dataclass
class SenderRecoveryState:
    desired_request: Any | None = None
    active_request: Any | None = None
    desired_mode: str | None = None
    active_mode: str | None = None
    phase: str = NORMAL_PHASE
    degraded_reason: str | None = None
    retry_count: int = 0
    next_retry_at: float | None = None
    last_failure: dict[str, Any] | None = None
    active_started_at: float | None = None
    stable_after: float | None = None


class SenderRecoveryPolicy:
    """Pure sender recovery state machine used by RuntimeService.

    The policy intentionally knows only about request attributes and uses
    dataclasses.replace() so tests can exercise fallback/backoff without
    importing the GStreamer-backed runtime modules.
    """

    def __init__(self) -> None:
        self.state = SenderRecoveryState()

    def reset(self) -> None:
        self.state = SenderRecoveryState()

    def begin(self, request: Any, now: float, preflight_errors: list[str] | None = None) -> Any:
        self.reset()
        desired_mode = sender_mode_for_request(request)
        self.state.desired_request = request
        self.state.desired_mode = desired_mode

        if desired_mode == PLAYBACK_DSP_MODE and preflight_errors:
            fallback = fallback_for_playback_failure(request)
            self.state.active_request = fallback
            self.state.active_mode = sender_mode_for_request(fallback)
            self.state.phase = DEGRADED_PHASE
            self.state.degraded_reason = "Playback + DSP preflight failed: " + "; ".join(preflight_errors)
            self.state.retry_count = 1
            self.state.next_retry_at = now + backoff_seconds(self.state.retry_count)
            self.state.active_started_at = now
            self.state.stable_after = None
            return fallback

        self.state.active_request = request
        self.state.active_mode = desired_mode
        self.state.phase = NORMAL_PHASE
        self.state.active_started_at = now
        self.state.stable_after = (
            now + HEALTHY_UPTIME_SECONDS if desired_mode == PLAYBACK_DSP_MODE else None
        )
        return request

    def launched(self, request: Any, now: float) -> None:
        self.state.active_request = request
        self.state.active_mode = sender_mode_for_request(request)
        self.state.active_started_at = now
        if self.state.active_mode == PLAYBACK_DSP_MODE:
            self.state.stable_after = now + HEALTHY_UPTIME_SECONDS
        else:
            self.state.stable_after = None

    def on_exit(self, exit_code: int, now: float) -> RecoveryAction:
        active_request = self.state.active_request
        active_mode = self.state.active_mode
        desired_request = self.state.desired_request
        desired_mode = self.state.desired_mode
        uptime = (
            max(0.0, now - self.state.active_started_at)
            if self.state.active_started_at is not None
            else 0.0
        )
        self.state.last_failure = {
            "exit_code": exit_code,
            "mode": active_mode,
            "uptime_seconds": round(uptime, 1),
        }

        if active_request is None or desired_request is None:
            self.state.phase = STOPPED_PHASE
            return RecoveryAction("stop", reason="Sender process exited without an active recovery target.")

        if desired_mode == PLAYBACK_DSP_MODE:
            if active_mode == PLAYBACK_DSP_MODE:
                fallback = fallback_for_playback_failure(desired_request)
                self._degrade_to(
                    fallback,
                    now,
                    f"Playback + DSP exited after {round(uptime, 1)}s with code {exit_code}.",
                    increment_retry=True,
                )
                return RecoveryAction("launch", fallback, self.state.degraded_reason)

            if active_mode == CAPTURE_ONLY_MODE:
                fallback = video_only_request(desired_request)
                self._degrade_to(
                    fallback,
                    now,
                    f"Capture-only fallback exited after {round(uptime, 1)}s with code {exit_code}; switching to video-only.",
                    increment_retry=False,
                )
                return RecoveryAction("launch", fallback, self.state.degraded_reason)

            self.state.phase = STOPPED_PHASE
            self.state.active_request = None
            self.state.active_mode = None
            self.state.degraded_reason = (
                f"Video-only fallback exited after {round(uptime, 1)}s with code {exit_code}."
            )
            return RecoveryAction("stop", reason=self.state.degraded_reason)

        if active_mode == CAPTURE_ONLY_MODE:
            fallback = video_only_request(desired_request)
            self._degrade_to(
                fallback,
                now,
                f"Capture-only sender exited after {round(uptime, 1)}s with code {exit_code}; switching to video-only.",
                increment_retry=False,
            )
            return RecoveryAction("launch", fallback, self.state.degraded_reason)

        self.state.phase = STOPPED_PHASE
        self.state.active_request = None
        self.state.active_mode = None
        return RecoveryAction("stop", reason=f"Sender exited with code {exit_code}.")

    def degrade_playback_stall(self, now: float, reason: str) -> RecoveryAction:
        active_request = self.state.active_request
        desired_request = self.state.desired_request
        if (
            active_request is None
            or desired_request is None
            or self.state.desired_mode != PLAYBACK_DSP_MODE
            or self.state.active_mode != PLAYBACK_DSP_MODE
        ):
            return RecoveryAction("noop", reason=reason)

        uptime = (
            max(0.0, now - self.state.active_started_at)
            if self.state.active_started_at is not None
            else 0.0
        )
        self.state.last_failure = {
            "exit_code": None,
            "mode": self.state.active_mode,
            "uptime_seconds": round(uptime, 1),
            "reason": "preview_watchdog",
        }
        fallback = fallback_for_playback_failure(desired_request)
        self._degrade_to(fallback, now, reason, increment_retry=True)
        return RecoveryAction("launch", fallback, reason)

    def due_for_retry(self, now: float) -> bool:
        return (
            self.state.desired_mode == PLAYBACK_DSP_MODE
            and self.state.phase == DEGRADED_PHASE
            and self.state.next_retry_at is not None
            and now >= self.state.next_retry_at
        )

    def defer_retry(self, now: float, reason: str) -> None:
        self.state.phase = DEGRADED_PHASE
        self.state.retry_count += 1
        self.state.next_retry_at = now + backoff_seconds(self.state.retry_count)
        self.state.degraded_reason = reason

    def prepare_restore_attempt(self, now: float) -> Any | None:
        if self.state.desired_request is None or self.state.desired_mode != PLAYBACK_DSP_MODE:
            return None
        self.state.phase = RESTORING_PHASE
        self.state.active_request = self.state.desired_request
        self.state.active_mode = PLAYBACK_DSP_MODE
        self.state.active_started_at = now
        self.state.stable_after = now + HEALTHY_UPTIME_SECONDS
        self.state.next_retry_at = None
        return self.state.desired_request

    def mark_stable(self, now: float) -> bool:
        if self.state.active_mode != PLAYBACK_DSP_MODE:
            return False
        if self.state.stable_after is not None and now < self.state.stable_after:
            return False
        self.state.phase = NORMAL_PHASE
        self.state.degraded_reason = None
        self.state.retry_count = 0
        self.state.next_retry_at = None
        self.state.last_failure = None
        self.state.stable_after = None
        return True

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            "desired_mode": self.state.desired_mode,
            "active_mode": self.state.active_mode,
            "phase": self.state.phase,
            "degraded": self.state.phase in {DEGRADED_PHASE, RESTORING_PHASE},
            "degraded_reason": self.state.degraded_reason,
            "retry_count": self.state.retry_count,
            "next_retry_at": self.state.next_retry_at,
            "next_retry_in_seconds": (
                max(0, int(self.state.next_retry_at - now))
                if self.state.next_retry_at is not None
                else None
            ),
            "last_failure": self.state.last_failure,
            "stable_after": self.state.stable_after,
            "stable_in_seconds": (
                max(0, int(self.state.stable_after - now))
                if self.state.stable_after is not None
                else None
            ),
        }

    def _degrade_to(self, request: Any, now: float, reason: str, *, increment_retry: bool) -> None:
        self.state.active_request = request
        self.state.active_mode = sender_mode_for_request(request)
        self.state.phase = DEGRADED_PHASE
        self.state.degraded_reason = reason
        self.state.active_started_at = now
        self.state.stable_after = None
        if self.state.desired_mode == PLAYBACK_DSP_MODE:
            if increment_retry:
                self.state.retry_count += 1
            elif self.state.retry_count == 0:
                self.state.retry_count = 1
            self.state.next_retry_at = now + backoff_seconds(self.state.retry_count)
        else:
            self.state.retry_count = 0
            self.state.next_retry_at = None


def sender_mode_for_request(request: Any | None) -> str | None:
    if request is None or getattr(request, "role", None) != "sender":
        return None
    if getattr(request, "audio_source", "off") == "off":
        return VIDEO_ONLY_MODE
    if getattr(request, "sender_audio_mode", "aec") == "aec":
        return PLAYBACK_DSP_MODE
    return CAPTURE_ONLY_MODE


def fallback_for_playback_failure(request: Any) -> Any:
    if getattr(request, "audio_source", "off") == "off":
        return video_only_request(request)
    return capture_only_request(request)


def capture_only_request(request: Any) -> Any:
    return replace(
        request,
        sender_audio_mode="capture-only",
        sender_playback_device=None,
        sender_audio_delay_ms=0,
    )


def video_only_request(request: Any) -> Any:
    return replace(
        request,
        audio_source="off",
        sender_audio_mode="capture-only",
        audio_device=None,
        sender_playback_device=None,
        sender_audio_delay_ms=0,
    )


def backoff_seconds(retry_count: int) -> float:
    index = max(0, min(retry_count - 1, len(RETRY_BACKOFF_SECONDS) - 1))
    return RETRY_BACKOFF_SECONDS[index]
