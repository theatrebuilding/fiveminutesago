from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_app.services import disconnect_fallback


class DisconnectFallbackTests(unittest.TestCase):
    def test_load_paragraphs_writes_successful_fetch_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "paragraphs.txt"

            paragraphs = disconnect_fallback.load_paragraphs(
                cache_path=cache_path,
                fetcher=lambda _url: ["Remote one", "Remote two"],
                defaults=["Default"],
            )

            self.assertEqual(paragraphs, ["Remote one", "Remote two"])
            self.assertEqual(
                disconnect_fallback.read_cached_paragraphs(cache_path),
                ["Remote one", "Remote two"],
            )

    def test_load_paragraphs_uses_cache_when_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "paragraphs.txt"
            disconnect_fallback.write_cached_paragraphs(cache_path, ["Cached one", "Cached two"])

            def fail(_url: str) -> list[str]:
                raise RuntimeError("offline")

            paragraphs = disconnect_fallback.load_paragraphs(
                cache_path=cache_path,
                fetcher=fail,
                defaults=["Default"],
            )

            self.assertEqual(paragraphs, ["Cached one", "Cached two"])

    def test_load_paragraphs_uses_defaults_when_fetch_and_cache_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing.txt"

            paragraphs = disconnect_fallback.load_paragraphs(
                cache_path=cache_path,
                fetcher=lambda _url: [],
                defaults=["Default one", "Default two"],
            )

            self.assertEqual(paragraphs, ["Default one", "Default two"])


if __name__ == "__main__":
    unittest.main()
