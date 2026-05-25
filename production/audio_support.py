from __future__ import annotations

from typing import Any


SUPPORTED_WEBRTC_SAMPLE_RATES = {8000, 16000, 32000, 48000}
COMMON_AUDIO_HARDWARE_RATES = [8000, 16000, 32000, 44100, 48000, 88200, 96000]
DEFAULT_AUDIO_CHANNEL_PAIR = [1, 2]
MAX_AUDIO_HARDWARE_CHANNELS = 64
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


def alsa_runtime_device(value: Any) -> str:
    """Return an ALSA device string suitable for app-managed rate/channel routing.

    Direct `hw:*` devices reject many otherwise convertible formats. The UI still
    displays the real `hw:*` device names discovered by ALSA, but runtime paths
    use `plughw:*` so ALSA can adapt sample format/rate/channel layout for USB
    interfaces such as Focusrite Scarlett devices.
    """

    normalized = str(value or "default").strip() or "default"
    if normalized.startswith("hw:"):
        return f"plughw:{normalized.removeprefix('hw:')}"
    return normalized


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


def validate_local_audio_rate(audio_rate: Any, *, fallback: int = 48000) -> int:
    if audio_rate is None or audio_rate == "":
        return fallback
    if isinstance(audio_rate, bool):
        raise ValueError("sender audio rate must be an integer sample rate.")
    try:
        rate = int(audio_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("sender audio rate must be an integer sample rate.") from exc
    if rate <= 0 or rate > 384000:
        raise ValueError("sender audio rate must be between 1 and 384000 Hz.")
    return rate


def normalize_audio_channel_pair(value: Any, field_name: str) -> list[int]:
    if value is None or value == "":
        return list(DEFAULT_AUDIO_CHANNEL_PAIR)
    if isinstance(value, str):
        cleaned = value.strip().replace("/", ",")
        try:
            parts = [int(part.strip()) for part in cleaned.split(",") if part.strip()]
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a stereo channel pair like 1/2.") from exc
    elif isinstance(value, (list, tuple)):
        try:
            parts = [int(part) for part in value]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a stereo channel pair like [1, 2].") from exc
    else:
        raise ValueError(f"{field_name} must be a stereo channel pair like [1, 2].")

    if len(parts) != 2:
        raise ValueError(f"{field_name} must contain exactly two channels.")
    left, right = parts
    if left < 1 or right < 1:
        raise ValueError(f"{field_name} channels are 1-based and must be positive.")
    if right != left + 1:
        raise ValueError(f"{field_name} must be a consecutive stereo pair.")
    if left % 2 != 1:
        raise ValueError(f"{field_name} must start on an odd channel: 1/2, 3/4, 5/6, ...")
    if right > MAX_AUDIO_HARDWARE_CHANNELS:
        raise ValueError(f"{field_name} cannot exceed channel {MAX_AUDIO_HARDWARE_CHANNELS}.")
    return [left, right]


def normalize_audio_hardware_channels(value: Any, channel_pair: Any, field_name: str) -> int:
    pair = normalize_audio_channel_pair(channel_pair, field_name.replace("hardware_channels", "channels"))
    minimum = max(pair)
    if value is None or value == "":
        return minimum
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer channel count.")
    try:
        channels = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer channel count.") from exc
    if channels < minimum:
        raise ValueError(f"{field_name} must be at least {minimum} for pair {pair[0]}/{pair[1]}.")
    if channels > MAX_AUDIO_HARDWARE_CHANNELS:
        raise ValueError(f"{field_name} cannot exceed {MAX_AUDIO_HARDWARE_CHANNELS}.")
    return channels


def choose_audio_hardware_channels(channel_pair: Any, supported_counts: Any = None) -> int:
    pair = normalize_audio_channel_pair(channel_pair, "channel pair")
    minimum = max(pair)
    if supported_counts:
        candidates: list[int] = []
        for value in supported_counts:
            try:
                channels = int(value)
            except (TypeError, ValueError):
                continue
            if minimum <= channels <= MAX_AUDIO_HARDWARE_CHANNELS:
                candidates.append(channels)
        if candidates:
            return min(candidates)
    return minimum


def channel_pairs_for_count(channel_count: Any, supported_counts: Any = None) -> list[dict[str, Any]]:
    try:
        count = int(channel_count)
    except (TypeError, ValueError):
        count = 2
    count = max(2, min(count, MAX_AUDIO_HARDWARE_CHANNELS))
    if count % 2:
        count -= 1
    return [
        {
            "value": f"{channel}/{channel + 1}",
            "label": f"Channels {channel}/{channel + 1}",
            "channels": [channel, channel + 1],
            "hardware_channels": choose_audio_hardware_channels([channel, channel + 1], supported_counts),
        }
        for channel in range(1, count + 1, 2)
    ]


def build_input_pair_mix_element(channel_pair: Any, hardware_channels: Any) -> str:
    pair = normalize_audio_channel_pair(channel_pair, "input channel pair")
    input_channels = normalize_audio_hardware_channels(hardware_channels, pair, "input hardware_channels")
    if pair == DEFAULT_AUDIO_CHANNEL_PAIR and input_channels == 2:
        return ""
    rows = [[0.0 for _ in range(input_channels)] for _ in range(2)]
    rows[0][pair[0] - 1] = 1.0
    rows[1][pair[1] - 1] = 1.0
    return (
        f'audiomixmatrix in-channels={input_channels} out-channels=2 '
        f'channel-mask=-1 matrix="{format_gst_mix_matrix(rows)}"'
    )


def build_output_pair_mix_element(channel_pair: Any, hardware_channels: Any) -> str:
    pair = normalize_audio_channel_pair(channel_pair, "output channel pair")
    output_channels = normalize_audio_hardware_channels(hardware_channels, pair, "output hardware_channels")
    if pair == DEFAULT_AUDIO_CHANNEL_PAIR and output_channels == 2:
        return ""
    rows = [[0.0, 0.0] for _ in range(output_channels)]
    rows[pair[0] - 1][0] = 1.0
    rows[pair[1] - 1][1] = 1.0
    return (
        f'audiomixmatrix in-channels=2 out-channels={output_channels} '
        f'channel-mask=-1 matrix="{format_gst_mix_matrix(rows)}"'
    )


def format_gst_mix_matrix(rows: list[list[float]]) -> str:
    formatted_rows = []
    for row in rows:
        formatted_rows.append("<" + ", ".join(f"(double){float(value):.1f}" for value in row) + ">")
    return "<" + ", ".join(formatted_rows) + ">"


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
