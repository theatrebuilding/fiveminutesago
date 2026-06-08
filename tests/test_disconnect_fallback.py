from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_app.services import disconnect_fallback


class DisconnectFallbackTests(unittest.TestCase):
    def test_load_paragraphs_reads_fallback_text_file_lines_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_path = Path(tmpdir) / "fallback.txt"
            fallback_path.write_text("First line\n\nSecond wrapped\nparagraph\n", encoding="utf-8")

            paragraphs = disconnect_fallback.load_paragraphs(fallback_text_file=fallback_path)

            self.assertEqual(paragraphs, ["First line", "Second wrapped paragraph"])

    def test_load_paragraphs_treats_line_script_as_individual_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_path = Path(tmpdir) / "fallback.txt"
            fallback_path.write_text("Line one\nLine two\nLine three\n", encoding="utf-8")

            paragraphs = disconnect_fallback.load_paragraphs(fallback_text_file=fallback_path)

            self.assertEqual(paragraphs, ["Line one", "Line two", "Line three"])

    def test_load_paragraphs_preserves_repeated_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_path = Path(tmpdir) / "fallback.txt"
            fallback_path.write_text("Repeat me\nRepeat me\n", encoding="utf-8")

            paragraphs = disconnect_fallback.load_paragraphs(fallback_text_file=fallback_path)

            self.assertEqual(paragraphs, ["Repeat me", "Repeat me"])

    def test_load_paragraphs_uses_defaults_when_file_is_missing_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_path = Path(tmpdir) / "missing.txt"

            paragraphs = disconnect_fallback.load_paragraphs(
                fallback_text_file=fallback_path,
                defaults=["Default one", "Default two"],
            )

            self.assertEqual(paragraphs, ["Default one", "Default two"])

    def test_paragraph_display_seconds_increases_with_word_count(self) -> None:
        short = disconnect_fallback.paragraph_display_seconds(
            "one two",
            min_seconds=5.0,
            seconds_per_word=0.5,
            max_seconds=20.0,
        )
        long = disconnect_fallback.paragraph_display_seconds(
            " ".join(["word"] * 14),
            min_seconds=5.0,
            seconds_per_word=0.5,
            max_seconds=20.0,
        )

        self.assertLess(short, long)
        self.assertEqual(short, 5.0)
        self.assertEqual(long, 7.0)

    def test_paragraph_display_seconds_is_capped(self) -> None:
        display_seconds = disconnect_fallback.paragraph_display_seconds(
            " ".join(["word"] * 100),
            min_seconds=1.0,
            seconds_per_word=1.0,
            max_seconds=12.0,
        )

        self.assertEqual(display_seconds, 12.0)


if __name__ == "__main__":
    unittest.main()
