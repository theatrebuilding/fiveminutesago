from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Iterable

WIDTH = 1920
HEIGHT = 1080
FONT_SIZE = 32
MARGIN = 180
DEFAULT_MIN_SECONDS_PER_PARAGRAPH = 5.0
DEFAULT_SECONDS_PER_WORD = 0.35
DEFAULT_MAX_SECONDS_PER_PARAGRAPH = 45.0
DEFAULT_FALLBACK_TEXT_FILE = Path(__file__).resolve().parents[2] / "fallback.txt"

DEFAULT_FALLBACK_PARAGRAPHS = [
    "Signal lost. Waiting for the live image to return.",
    "The connection is temporarily absent, but the receiver is still listening.",
    "No stream is currently visible. The receiver will automatically rejoin when the signal returns.",
]


def read_text_file_paragraphs(path: str | Path | None) -> list[str]:
    if path is None:
        return []

    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []

    if not raw_text.strip():
        return []

    blocks = raw_text.split("\n\n")
    if len(blocks) == 1:
        # fallback.txt is script-like: each non-empty line is an on-screen unit.
        candidates = raw_text.splitlines()
    else:
        # Conventional paragraph files can use blank lines to wrap paragraphs.
        candidates = blocks

    paragraphs = []
    for candidate in candidates:
        paragraph = " ".join(candidate.split())
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def load_paragraphs(
    *,
    fallback_text_file: str | Path | None = DEFAULT_FALLBACK_TEXT_FILE,
    defaults: Iterable[str] = DEFAULT_FALLBACK_PARAGRAPHS,
) -> list[str]:
    paragraphs = read_text_file_paragraphs(fallback_text_file)
    if paragraphs:
        return paragraphs
    return list(defaults)


def shuffle_paragraphs(paragraphs: Iterable[str]) -> list[str]:
    shuffled = list(paragraphs)
    random.shuffle(shuffled)
    return shuffled


def paragraph_display_seconds(
    paragraph: str,
    *,
    min_seconds: float = DEFAULT_MIN_SECONDS_PER_PARAGRAPH,
    seconds_per_word: float = DEFAULT_SECONDS_PER_WORD,
    max_seconds: float = DEFAULT_MAX_SECONDS_PER_PARAGRAPH,
) -> float:
    word_count = len(str(paragraph).split())
    display_seconds = max(min_seconds, word_count * seconds_per_word)
    return min(max_seconds, display_seconds)


class DisconnectFallbackTextSource:
    def __init__(
        self,
        *,
        fallback_text_file: str | Path | None = DEFAULT_FALLBACK_TEXT_FILE,
        defaults: Iterable[str] = DEFAULT_FALLBACK_PARAGRAPHS,
    ) -> None:
        self.fallback_text_file = fallback_text_file
        self.defaults = list(defaults)
        self._paragraphs = shuffle_paragraphs(
            load_paragraphs(
                fallback_text_file=fallback_text_file,
                defaults=self.defaults,
            )
        )

    def paragraphs(self) -> list[str]:
        return list(self._paragraphs)

    def refresh(self) -> None:
        self._paragraphs = shuffle_paragraphs(
            load_paragraphs(
                fallback_text_file=self.fallback_text_file,
                defaults=self.defaults,
            )
        )


class DisconnectFallbackFrameSource:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        font_size: int = FONT_SIZE,
        margin: int | None = None,
        fallback_text_file: str | Path | None = DEFAULT_FALLBACK_TEXT_FILE,
        min_seconds_per_paragraph: float = DEFAULT_MIN_SECONDS_PER_PARAGRAPH,
        seconds_per_word: float = DEFAULT_SECONDS_PER_WORD,
        max_seconds_per_paragraph: float = DEFAULT_MAX_SECONDS_PER_PARAGRAPH,
    ) -> None:
        self.width = width
        self.height = height
        self.font_size = font_size
        self.margin = margin if margin is not None else max(40, int(width * 0.07))
        self.min_seconds_per_paragraph = min_seconds_per_paragraph
        self.seconds_per_word = seconds_per_word
        self.max_seconds_per_paragraph = max_seconds_per_paragraph
        self.text_source = DisconnectFallbackTextSource(fallback_text_file=fallback_text_file)
        self.index = 0
        self.last_change = 0.0
        self.current_paragraph: str | None = None
        self._pygame = None
        self._surface = None
        self._font = None

    def frame(self, now: float | None = None) -> bytes:
        now = time.time() if now is None else now
        paragraph = self._current_paragraph(now)
        pygame = self._ensure_pygame()
        draw_paragraph(
            self._surface,
            self._font,
            paragraph,
            width=self.width,
            height=self.height,
            margin=self.margin,
            update_display=False,
        )
        return pygame.image.tostring(self._surface, "RGB")

    def _current_paragraph(self, now: float) -> str:
        paragraphs = self.text_source.paragraphs()
        if not paragraphs:
            paragraphs = list(DEFAULT_FALLBACK_PARAGRAPHS)

        current_display_seconds = (
            paragraph_display_seconds(
                self.current_paragraph,
                min_seconds=self.min_seconds_per_paragraph,
                seconds_per_word=self.seconds_per_word,
                max_seconds=self.max_seconds_per_paragraph,
            )
            if self.current_paragraph is not None
            else 0.0
        )

        if self.current_paragraph is None or now - self.last_change >= current_display_seconds:
            if self.index >= len(paragraphs):
                random.shuffle(paragraphs)
                self.index = 0
            self.current_paragraph = paragraphs[self.index]
            self.index += 1
            self.last_change = now
        return self.current_paragraph

    def _ensure_pygame(self):
        if self._pygame is not None:
            return self._pygame

        import pygame

        pygame.font.init()
        self._surface = pygame.Surface((self.width, self.height))
        self._font = pygame.font.SysFont("Arial", self.font_size)
        self._pygame = pygame
        return pygame


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = current + (" " if current else "") + word
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def draw_paragraph(
    screen,
    font,
    paragraph,
    *,
    width=WIDTH,
    height=HEIGHT,
    margin=MARGIN,
    update_display=True,
):
    import pygame

    screen.fill((0, 0, 0))

    max_width = width - 2 * margin
    lines = wrap_text(paragraph, font, max_width)

    line_height = font.get_linesize()
    total_height = len(lines) * line_height
    y = max((height - total_height) // 2, margin)

    for line in lines:
        surface = font.render(line, True, (255, 255, 255))
        rect = surface.get_rect(center=(width // 2, y + line_height // 2))
        screen.blit(surface, rect)
        y += line_height

    if update_display:
        pygame.display.flip()


def main():
    import pygame

    text_source = DisconnectFallbackTextSource()

    pygame.init()
    pygame.display.set_caption("Disconnect Fallback")

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    width, height = screen.get_size()
    font = pygame.font.SysFont("Arial", FONT_SIZE)
    margin = max(40, int(width * 0.07))

    index = 0
    running = True
    last_change = 0.0
    current_paragraph = None

    while running:
        now = time.time()
        paragraphs = text_source.paragraphs() or list(DEFAULT_FALLBACK_PARAGRAPHS)
        current_display_seconds = paragraph_display_seconds(current_paragraph) if current_paragraph else 0.0

        if current_paragraph is None or now - last_change >= current_display_seconds:
            if index >= len(paragraphs):
                random.shuffle(paragraphs)
                index = 0

            current_paragraph = paragraphs[index]
            draw_paragraph(screen, font, current_paragraph, width=width, height=height, margin=margin)
            index += 1
            last_change = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                if event.key == pygame.K_SPACE:
                    if index >= len(paragraphs):
                        random.shuffle(paragraphs)
                        index = 0

                    current_paragraph = paragraphs[index]
                    draw_paragraph(screen, font, current_paragraph, width=width, height=height, margin=margin)
                    index += 1
                    last_change = time.time()

    pygame.quit()


if __name__ == "__main__":
    main()
