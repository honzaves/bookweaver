"""
epub_io.py
----------
Shared EPUB → chapter extraction. The single source of truth for turning
an EPUB into an ordered list of Chapter records, used by both app.py (to
build the chapter-selection list) and worker.py (to process). Positional
chapter indices are stable between those two reads only because both go
through extract_chapters() — never reimplement extraction elsewhere.

Imports ebooklib / bs4 only. Never Qt, app, worker, or settings.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# A document with more than this many characters of text is a chapter;
# shorter documents (cover, nav) are skipped. The checkbox list lets the
# user deselect anything that slips past this heuristic.
MIN_CHAPTER_CHARS = 200

# Out-of-prose marker for a scene break. The Unicode "symbol for record
# separator" never occurs in book text, so it round-trips safely and is
# stripped before any prompt or output write (see worker._split_into_chunks_with_scenes).
SCENE_BREAK = "␞"

# A line consisting only of a scene-break separator: '* * *' (2+ stars),
# a run of 3+ dashes/asterisks, or an asterism '⁂'.
_SEPARATOR_LINE = re.compile(
    r"^\s*(?:\*\s*){2,}\*?\s*$|^\s*[*–—\-]{3,}\s*$|^\s*⁂+\s*$"
)


@dataclass(frozen=True)
class Chapter:
    """One processable chapter. `index` is the stable 0-based position in
    the extracted list and is used as the selection identifier."""
    index: int
    doc_name: str
    title: str
    text: str


def _basename(href: str) -> str:
    """Strip any #anchor and directory path from a TOC href."""
    return href.split("#", 1)[0].rsplit("/", 1)[-1]


def _flatten_toc(toc) -> dict[str, str]:
    """Map basename(href) -> title across a (possibly nested) book.toc.

    book.toc entries are epub.Link, epub.Section, or (head, [children])
    tuples. Only Links carry an href+title we can map to a document."""
    mapping: dict[str, str] = {}

    def walk(entries) -> None:
        for entry in entries:
            if isinstance(entry, (tuple, list)):
                walk_entry(entry[0])
                if len(entry) > 1 and isinstance(entry[1], (list, tuple)):
                    walk(entry[1])
            else:
                walk_entry(entry)

    def walk_entry(entry) -> None:
        href = getattr(entry, "href", None)
        title = getattr(entry, "title", None)
        if href and title:
            mapping.setdefault(_basename(href), title.strip())

    walk(toc)
    return mapping


def _resolve_title(doc_name: str, soup: BeautifulSoup,
                   toc_map: dict[str, str], preview_chars: int) -> str:
    """TOC title → first heading → text preview → bare filename."""
    base = _basename(doc_name)
    if toc_map.get(base):
        return toc_map[base]
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    preview = soup.get_text(separator=" ", strip=True)[:preview_chars].strip()
    return preview or base


def _mark_separator_lines(text: str) -> str:
    """Replace separator-only lines ('* * *', '⁂', '———') with SCENE_BREAK."""
    out = []
    for line in text.split("\n"):
        out.append(SCENE_BREAK if _SEPARATOR_LINE.match(line) else line)
    return "\n".join(out)


def extract_chapters(path: str, preview_chars: int = 50,
                     mark_scene_breaks: bool = False) -> list[Chapter]:
    """Read *path* and return its chapters in document order.

    When *mark_scene_breaks* is True, scene breaks (<hr> elements and
    separator-only lines like '* * *') are represented in Chapter.text as a
    lone SCENE_BREAK paragraph, for the worker's scene-gated prose carry.
    Default False keeps text byte-identical to a plain extraction. The
    length filter and title are always computed on the UNMARKED text, so
    chapter count, indices, and titles match a plain extraction exactly."""
    book = epub.read_epub(path)
    toc_map = _flatten_toc(book.toc)
    chapters: list[Chapter] = []
    idx = 0
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Filter and title use the unmarked text/soup: the app extracts
        # without marking, and inclusion/index/title parity between the two
        # reads is what keeps selected_chapters aligned (module docstring).
        # Mutating the soup first would also let the sentinel leak into a
        # preview-fallback title.
        text = soup.get_text(separator="\n").strip()
        if len(text) > MIN_CHAPTER_CHARS:
            title = _resolve_title(item.get_name(), soup, toc_map, preview_chars)
            if mark_scene_breaks:
                for hr in soup.find_all("hr"):
                    hr.replace_with(f"\n{SCENE_BREAK}\n")
                text = _mark_separator_lines(
                    soup.get_text(separator="\n").strip()
                )
            chapters.append(Chapter(idx, item.get_name(), title, text))
            idx += 1
    return chapters


def select_chapters(chapters: list[Chapter],
                    indices: Iterable[int] | None) -> list[Chapter]:
    """Filter *chapters* to those whose .index is in *indices*, preserving
    document order. `indices is None` means 'all chapters'."""
    if indices is None:
        return chapters
    wanted = set(indices)
    return [c for c in chapters if c.index in wanted]
