from __future__ import annotations

import datetime as dt
from pathlib import Path
import time
from typing import Any


VALID_PREVIEW_FEEDS = {"tn", "dk"}


def build_server_preview_pattern(preview_dir: Path, feed: str) -> str:
    normalized_feed = _normalize_feed(feed)
    return str(preview_dir / f"{normalized_feed}-preview-%05d.jpg")


def build_receiver_preview_pattern(preview_dir: Path, country: str) -> str:
    normalized_country = _normalize_feed(country)
    return str(preview_dir / f"receiver-{normalized_country}-preview-%05d.jpg")


def describe_latest_preview(preview_dir: Path, pattern: str) -> dict[str, Any]:
    prefix = Path(pattern).name.split("%", 1)[0]
    candidates = sorted(
        preview_dir.glob(f"{prefix}*.jpg"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {
            "available": False,
            "path": None,
            "updated_at": None,
            "updated_at_ts": None,
            "age_seconds": None,
        }

    latest = candidates[0]
    modified_at = latest.stat().st_mtime
    return {
        "available": True,
        "path": str(latest),
        "updated_at": _to_iso(modified_at),
        "updated_at_ts": modified_at,
        "age_seconds": max(0, int(time.time() - modified_at)),
    }


def _normalize_feed(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in VALID_PREVIEW_FEEDS:
        raise ValueError(f"Unsupported preview feed: {value}")
    return normalized


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
