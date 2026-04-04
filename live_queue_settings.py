from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_queue_element(
    config: Mapping[str, Any] | None,
    path: Sequence[str],
    defaults: Mapping[str, Any],
    *,
    factory: str = "queue",
) -> str:
    properties = build_queue_properties(config, path, defaults)
    if not properties:
        return factory
    return f"{factory} {properties}"


def build_queue_properties(
    config: Mapping[str, Any] | None,
    path: Sequence[str],
    defaults: Mapping[str, Any],
) -> str:
    settings = dict(defaults)
    override = _lookup_queue_override(config, path)
    if override is not None:
        settings.update(override)

    parts: list[str] = []
    leaky = _normalize_leaky(settings.get("leaky"))
    if leaky is not None:
        parts.append(f"leaky={leaky}")

    max_size_buffers = _to_int_or_none(settings.get("max_size_buffers"))
    if max_size_buffers is not None:
        parts.append(f"max-size-buffers={max_size_buffers}")

    max_size_bytes = _to_int_or_none(settings.get("max_size_bytes"))
    if max_size_bytes is not None:
        parts.append(f"max-size-bytes={max_size_bytes}")

    max_size_time_ns = _resolve_max_size_time_ns(settings)
    if max_size_time_ns is not None:
        parts.append(f"max-size-time={max_size_time_ns}")

    return " ".join(parts)


def _lookup_queue_override(
    config: Mapping[str, Any] | None,
    path: Sequence[str],
) -> dict[str, Any] | None:
    if not isinstance(config, Mapping):
        return None
    current: Any = config.get("live_queues")
    for segment in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    if not isinstance(current, Mapping):
        return None
    return dict(current)


def _normalize_leaky(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized or normalized in {"none", "no", "false"}:
        return None
    if normalized not in {"upstream", "downstream"}:
        raise ValueError(
            "Queue leaky must be one of: downstream, upstream, none."
        )
    return normalized


def _resolve_max_size_time_ns(settings: Mapping[str, Any]) -> int | None:
    if "max_size_time_ns" in settings and settings.get("max_size_time_ns") is not None:
        return _to_int_or_none(settings.get("max_size_time_ns"))
    if "max_size_time_ms" in settings and settings.get("max_size_time_ms") is not None:
        milliseconds = _to_int_or_none(settings.get("max_size_time_ms"))
        if milliseconds is None:
            return None
        return milliseconds * 1_000_000
    return None


def _to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
