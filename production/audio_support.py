from __future__ import annotations

from typing import Any


SUPPORTED_WEBRTC_SAMPLE_RATES = {8000, 16000, 32000, 48000}
SUPPORTED_MPEGTS_LPCM_SAMPLE_RATES = {48000, 96000}
SUPPORTED_MPEGTS_LPCM_FORMATS = {
    "S16BE": 16,
}
WEBRTC_DSP_PROPERTY_ORDER = [
    "compression-gain-db",
    "delay-agnostic",
    "echo-cancel",
    "echo-suppression-level",
    "experimental-agc",
    "extended-filter",
    "gain-control",
    "gain-control-mode",
    "high-pass-filter",
    "limiter",
    "noise-suppression",
    "noise-suppression-level",
    "startup-min-volume",
    "target-level-dbfs",
    "voice-detection",
    "voice-detection-frame-size-ms",
    "voice-detection-likelihood",
]
WEBRTC_DSP_DEFAULTS = {
    "compression-gain-db": 9,
    "delay-agnostic": False,
    "echo-cancel": True,
    "echo-suppression-level": "moderate",
    "experimental-agc": False,
    "extended-filter": False,
    "gain-control": True,
    "gain-control-mode": "adaptive-digital",
    "high-pass-filter": True,
    "limiter": True,
    "noise-suppression": True,
    "noise-suppression-level": "moderate",
    "startup-min-volume": 12,
    "target-level-dbfs": 3,
    "voice-detection": False,
    "voice-detection-frame-size-ms": 0,
    "voice-detection-likelihood": "low",
}
WEBRTC_DSP_ENUM_VALUES = {
    "echo-suppression-level": {"low", "moderate", "high"},
    "gain-control-mode": {"adaptive-digital", "fixed-digital", "adaptive-analog"},
    "noise-suppression-level": {"low", "moderate", "high", "very-high"},
    "voice-detection-likelihood": {"very-low", "low", "moderate", "high"},
}
WEBRTC_DSP_BOOL_KEYS = {
    "delay-agnostic",
    "echo-cancel",
    "experimental-agc",
    "extended-filter",
    "gain-control",
    "high-pass-filter",
    "limiter",
    "noise-suppression",
    "voice-detection",
}
WEBRTC_DSP_INT_KEYS = {
    "compression-gain-db",
    "startup-min-volume",
    "target-level-dbfs",
    "voice-detection-frame-size-ms",
}


def gst_escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def validate_audio_rate(audio_rate: Any) -> int:
    try:
        rate = int(audio_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"audio.rate must be an integer supported by webrtcdsp; got {audio_rate!r}."
        ) from exc

    if rate not in SUPPORTED_WEBRTC_SAMPLE_RATES:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_WEBRTC_SAMPLE_RATES))
        raise ValueError(
            f"audio.rate={rate} is not supported by webrtcdsp. Use one of: {supported}."
        )

    return rate


def validate_mpegts_lpcm_config(audio_format: Any, audio_rate: Any) -> tuple[str, int, int]:
    normalized_format = str(audio_format or "S16BE").strip().upper()
    width = SUPPORTED_MPEGTS_LPCM_FORMATS.get(normalized_format)
    if width is None:
        supported_formats = ", ".join(sorted(SUPPORTED_MPEGTS_LPCM_FORMATS))
        raise ValueError(
            f"audio.format={normalized_format!r} is not supported for MPEG-TS LPCM. "
            f"Use one of: {supported_formats}."
        )

    try:
        rate = int(audio_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"audio.rate must be an integer supported by MPEG-TS LPCM; got {audio_rate!r}."
        ) from exc

    if rate not in SUPPORTED_MPEGTS_LPCM_SAMPLE_RATES:
        supported_rates = ", ".join(str(value) for value in sorted(SUPPORTED_MPEGTS_LPCM_SAMPLE_RATES))
        raise ValueError(
            f"audio.rate={rate} is not supported for MPEG-TS LPCM. Use one of: {supported_rates}."
        )

    return normalized_format, width, rate


def build_webrtcdsp_properties(dsp_cfg: Any) -> tuple[str, dict[str, Any]]:
    if dsp_cfg is None:
        dsp_cfg = {}
    if not isinstance(dsp_cfg, dict):
        raise ValueError("webrtcdsp_settings must be a YAML mapping.")

    unknown_keys = sorted(set(dsp_cfg) - set(WEBRTC_DSP_PROPERTY_ORDER))
    if unknown_keys:
        raise ValueError(
            "Unsupported webrtcdsp_settings keys: "
            + ", ".join(unknown_keys)
            + ". Remove them or map them to real webrtcdsp properties."
        )

    resolved: dict[str, Any] = {}
    properties: list[str] = []
    for key in WEBRTC_DSP_PROPERTY_ORDER:
        raw_value = dsp_cfg.get(key, WEBRTC_DSP_DEFAULTS[key])
        resolved_value = _normalize_dsp_value(key, raw_value)
        resolved[key] = resolved_value
        properties.append(f"{key}={_format_gst_value(resolved_value)}")

    return " ".join(properties), resolved


def _normalize_dsp_value(key: str, value: Any) -> Any:
    if key in WEBRTC_DSP_BOOL_KEYS:
        return _normalize_bool(key, value)
    if key in WEBRTC_DSP_INT_KEYS:
        return _normalize_int(key, value)
    if key in WEBRTC_DSP_ENUM_VALUES:
        return _normalize_enum(key, value, WEBRTC_DSP_ENUM_VALUES[key])
    raise ValueError(f"Unsupported webrtcdsp property mapping for {key}.")


def _normalize_bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ValueError(f"webrtcdsp_settings.{key} must be a boolean; got {value!r}.")


def _normalize_int(key: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"webrtcdsp_settings.{key} must be an integer; got {value!r}.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"webrtcdsp_settings.{key} must be an integer; got {value!r}.") from exc


def _normalize_enum(key: str, value: Any, allowed_values: set[str]) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"webrtcdsp_settings.{key} must be one of {sorted(allowed_values)}; got {value!r}."
        )
    normalized = value.strip().lower()
    if normalized not in allowed_values:
        raise ValueError(
            f"webrtcdsp_settings.{key} must be one of {sorted(allowed_values)}; got {value!r}."
        )
    return normalized


def _format_gst_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    return str(value)
