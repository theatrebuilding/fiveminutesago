from __future__ import annotations

import random
import threading
import textwrap
import time
from pathlib import Path
from typing import Callable, Iterable

URL = "https://thepostculturalbody.pubpub.org/pub/seacable/draft?access=xb7qo1am"

WIDTH = 1280
HEIGHT = 720
FONT_SIZE = 44
MARGIN = 90
SECONDS_PER_PARAGRAPH = 7
CACHE_MAX_PARAGRAPHS = 200

DEFAULT_FALLBACK_PARAGRAPHS = [
    "Signal lost. Waiting for the live image to return.",
    "The connection is temporarily absent, but the receiver is still listening.",
    "No stream is currently visible. The receiver will automatically rejoin when the signal returns.",
]

ParagraphFetcher = Callable[[str], list[str]]


def fetch_paragraphs(url: str) -> list[str]:
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Prefer actual paragraph tags.
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]

    # Fallback: split visible page text into blocks.
    if len(paragraphs) < 5:
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Roughly discard interface text before the actual document body.
        start_markers = [
            "Published under CC BY-SA 4.0",
            "spect-actor:",
            "الممثل-المتفرج:",
        ]

        start_index = 0
        for i, line in enumerate(lines):
            if any(marker in line for marker in start_markers):
                start_index = i
                break

        paragraphs = lines[start_index:]

    # Remove obvious UI fragments and tiny junk.
    junk = {
        "Search",
        "Dashboard",
        "Login",
        "Sharing",
        "Cite",
        "Download",
        "Comments",
        "License",
    }

    cleaned = []
    for para in paragraphs:
        para = " ".join(para.split())
        if len(para) < 3:
            continue
        if para in junk:
            continue
        if para not in cleaned:
            cleaned.append(para)

    random.shuffle(cleaned)
    return cleaned


def read_cached_paragraphs(cache_path: str | Path | None) -> list[str]:
    if cache_path is None:
        return []

    try:
        raw_text = Path(cache_path).read_text(encoding="utf-8")
    except OSError:
        return []

    paragraphs = []
    for block in raw_text.split("\n\n"):
        paragraph = " ".join(block.split())
        if paragraph and paragraph not in paragraphs:
            paragraphs.append(paragraph)
    return paragraphs


def write_cached_paragraphs(cache_path: str | Path | None, paragraphs: Iterable[str]) -> None:
    if cache_path is None:
        return

    cleaned = []
    for paragraph in paragraphs:
        paragraph = " ".join(str(paragraph).split())
        if paragraph and paragraph not in cleaned:
            cleaned.append(paragraph)
        if len(cleaned) >= CACHE_MAX_PARAGRAPHS:
            break

    if not cleaned:
        return

    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(cleaned) + "\n", encoding="utf-8")


def load_paragraphs(
    *,
    url: str = URL,
    cache_path: str | Path | None = None,
    fetcher: ParagraphFetcher = fetch_paragraphs,
    defaults: Iterable[str] = DEFAULT_FALLBACK_PARAGRAPHS,
) -> list[str]:
    try:
        fetched = fetcher(url)
    except Exception:
        fetched = []

    if fetched:
        write_cached_paragraphs(cache_path, fetched)
        return list(fetched)

    cached = read_cached_paragraphs(cache_path)
    if cached:
        return cached

    return list(defaults)


def load_cached_or_default(
    cache_path: str | Path | None = None,
    defaults: Iterable[str] = DEFAULT_FALLBACK_PARAGRAPHS,
) -> list[str]:
    cached = read_cached_paragraphs(cache_path)
    return cached or list(defaults)


class DisconnectFallbackTextSource:
    def __init__(
        self,
        *,
        url: str = URL,
        cache_path: str | Path | None = None,
        fetcher: ParagraphFetcher = fetch_paragraphs,
        async_refresh: bool = True,
        defaults: Iterable[str] = DEFAULT_FALLBACK_PARAGRAPHS,
    ) -> None:
        self.url = url
        self.cache_path = cache_path
        self.fetcher = fetcher
        self.defaults = list(defaults)
        self._lock = threading.Lock()
        self._paragraphs = load_cached_or_default(cache_path, self.defaults)
        if async_refresh:
            threading.Thread(target=self.refresh, name="disconnect-fallback-refresh", daemon=True).start()

    def paragraphs(self) -> list[str]:
        with self._lock:
            return list(self._paragraphs)

    def refresh(self) -> None:
        try:
            fetched = self.fetcher(self.url)
        except Exception as exc:
            print(f"DisconnectFallback: Could not refresh fallback text: {exc}", flush=True)
            return

        if not fetched:
            return

        write_cached_paragraphs(self.cache_path, fetched)
        with self._lock:
            self._paragraphs = list(fetched)


class DisconnectFallbackFrameSource:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        font_size: int = FONT_SIZE,
        margin: int | None = None,
        seconds_per_paragraph: int = SECONDS_PER_PARAGRAPH,
        cache_path: str | Path | None = None,
        url: str = URL,
    ) -> None:
        self.width = width
        self.height = height
        self.font_size = font_size
        self.margin = margin if margin is not None else max(40, int(width * 0.07))
        self.seconds_per_paragraph = seconds_per_paragraph
        self.text_source = DisconnectFallbackTextSource(url=url, cache_path=cache_path)
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

        if self.current_paragraph is None or now - self.last_change >= self.seconds_per_paragraph:
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
    pygame.display.set_caption("Random PubPub Paragraphs")

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    width, height = screen.get_size()
    font = pygame.font.SysFont("Arial", FONT_SIZE)
    margin = max(40, int(width * 0.07))

    index = 0
    running = True
    last_change = 0.0

    while running:
        now = time.time()
        paragraphs = text_source.paragraphs() or list(DEFAULT_FALLBACK_PARAGRAPHS)

        if now - last_change >= SECONDS_PER_PARAGRAPH:
            if index >= len(paragraphs):
                random.shuffle(paragraphs)
                index = 0

            draw_paragraph(screen, font, paragraphs[index], width=width, height=height, margin=margin)
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

                    draw_paragraph(screen, font, paragraphs[index], width=width, height=height, margin=margin)
                    index += 1
                    last_change = time.time()

    pygame.quit()


if __name__ == "__main__":
    main()
