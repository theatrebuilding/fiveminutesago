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


def build_sender_preview_pattern(preview_dir: Path, country: str) -> str:
    normalized_country = _normalize_feed(country)
    return str(preview_dir / f"sender-{normalized_country}-preview-%05d.jpg")


def describe_latest_preview(preview_dir: Path, pattern: str) -> dict[str, Any]:
    candidates = _preview_candidates(preview_dir, pattern)
    if not candidates:
        return {
            "available": False,
            "path": None,
            "updated_at": None,
            "updated_at_ts": None,
            "age_seconds": None,
        }

    latest = _select_settled_preview(candidates)
    modified_at = latest.stat().st_mtime
    return {
        "available": True,
        "path": str(latest),
        "updated_at": _to_iso(modified_at),
        "updated_at_ts": modified_at,
        "age_seconds": max(0, int(time.time() - modified_at)),
    }


def prune_preview_files(preview_dir: Path, pattern: str, keep: int = 0) -> None:
    candidates = _preview_candidates(preview_dir, pattern)
    for path in candidates[keep:]:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _preview_candidates(preview_dir: Path, pattern: str) -> list[Path]:
    prefix = Path(pattern).name.split("%", 1)[0]
    return sorted(
        preview_dir.glob(f"{prefix}*.jpg"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _select_settled_preview(candidates: list[Path]) -> Path:
    latest = candidates[0]
    if len(candidates) == 1:
        return latest

    if (time.time() - latest.stat().st_mtime) < 1:
        return candidates[1]
    return latest


def _normalize_feed(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in VALID_PREVIEW_FEEDS:
        raise ValueError(f"Unsupported preview feed: {value}")
    return normalized


def _to_iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
