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

# HTML block-level elements — the commonly cited block list plus our own
# additions (not a normative set from the standard). Every element NOT in
# here is treated as inline and flattened by
# _flatten_inline(), so a tag we have never seen defaults to inline. That
# is the safe direction: missing an inline tag re-splits sentences,
# whereas treating a rare tag as inline merely joins adjacent text.
#
# Two deliberate additions to the standard block list:
#   <br>  — the standard calls it inline, but it is a line break the
#           author intended; flattening it would run verse together.
#   document skeleton and table internals — unwrapping these would merge
#           table cells or leak stylesheet text into the prose.
_BLOCK_ELEMENTS: frozenset[str] = frozenset({
    "address", "article", "aside", "blockquote", "canvas", "center",
    "dd", "details", "dialog", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hgroup", "hr", "li", "main", "nav",
    "noscript", "ol", "p", "pre", "section", "table", "tfoot", "ul",
    "video",
    "br", "html", "head", "body", "title", "script", "style", "meta",
    "link", "tr", "td", "th", "thead", "tbody", "caption", "col",
    "colgroup",
})


def _flatten_inline(soup) -> None:
    """Unwrap inline elements, hoisting their children in place.

    get_text(separator="\\n") inserts its separator between adjacent
    string nodes, so `<i>`/`<span>`/`<b>` inside a paragraph split the
    sentence — and sometimes a word ("hyper<i>text</i>") — across lines.
    Flattening them first keeps the sentence whole while leaving block
    structure alone.

    unwrap() (not replace_with(get_text())) so that a `<br>`/`<hr>`/block
    element nested inside an inline tag survives — get_text() would
    concatenate across it and fuse the words on either side.

    smooth() is required, not cosmetic: unwrap() leaves the hoisted
    strings as separate nodes, so without the merge the separator is
    still inserted and this function silently does nothing.
    """
    for tag in [t for t in soup.find_all(True)
                if t.name not in _BLOCK_ELEMENTS]:
        tag.unwrap()
    soup.smooth()


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
                   toc_map: dict[str, str],
                   preview_chars: int) -> tuple[str, str]:
    """TOC title → first heading → text preview → bare filename.

    Returns `(title, source)` where source is one of "toc", "heading",
    "title", "preview", "filename". The caller needs the provenance:
    only "toc" and "heading" titles are safe to strip from the body
    (`_strip_title_heading`). A "preview" title is *made of* the body's
    opening prose, and a `<title>` is often the book's, not the chapter's."""
    base = _basename(doc_name)
    if toc_map.get(base):
        return toc_map[base], "toc"
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True), (
                "title" if tag == "title" else "heading"
            )
    preview = soup.get_text(separator=" ", strip=True)[:preview_chars].strip()
    return (preview, "preview") if preview else (base, "filename")


def _normalize_for_match(text: str) -> str:
    """Reduce *text* to casefolded alphanumerics for title/heading
    comparison. Drops whitespace, punctuation and curly quotes, so
    'CHAPTER 5\\nDUALITY' and 'Chapter 5 Duality' compare equal."""
    return "".join(c for c in text.casefold() if c.isalnum())


#  Containers we will descend *through* to find the real content root.
#  Deliberately excludes p/h1-h6/span: descending into those would let the
#  heading scan consume inline fragments and split a paragraph mid-sentence.
_WRAPPER_TAGS = {"body", "div", "section", "article", "main"}

#  A whole element that is nothing but a structural label ('CHAPTER 1',
#  'PART IV', '7'). Matched against fully-normalized element text, so the
#  roman-numeral class can only fire on an element that is *entirely* such
#  a word — verified across the 494 strip-eligible chapters in books/ with
#  no false positives.
_LABEL_ONLY = re.compile(r"^(?:chapter|part|section|book)?[0-9ivxlcdm]+$")

#  The same label at the START of a normalized title ('1. Capitalism' →
#  '1capitalism'). Digits only: stripping a roman-numeral prefix here would
#  eat the leading 'i' of titles like 'I Promise'.
_TITLE_LABEL_PREFIX = re.compile(r"^(?:chapter|part|section|book)?\d+")


def _content_root(soup: BeautifulSoup):
    """The element whose children are the chapter's top-level blocks.

    Many EPUBs wrap an entire chapter in a single `<div>`, which would
    leave `<body>` with one child holding both the heading and all the
    prose — indistinguishable from a chapter with no heading. Descend
    while the current node's only element child is itself a block
    wrapper."""
    node = soup.find("body") or soup
    while True:
        children = node.find_all(recursive=False)
        if len(children) != 1 or children[0].name not in _WRAPPER_TAGS:
            return node
        node = children[0]


def _strip_title_heading(soup: BeautifulSoup, title: str) -> None:
    """Remove the chapter's own display heading from *soup*, in place.

    The heading is redundant — the worker prepends the resolved title to
    every chapter block itself — and actively harmful: left in the body it
    reaches the LLM as source text, which echoes it into the summary, so
    the title lands in the output twice.

    Publishers mark headings up too variously to match on tag or class
    (one real book wraps `<p class="chap">CHAPTER 1</p>` and `<h2>` in a
    `<div class="head">`), so this consumes *leading elements* while their
    accumulated normalized text is a prefix of the normalized title, and
    removes them only on a **complete** match. A partial match strips
    nothing: 'CHAPTER 3' alone under the title 'Chapter 3 Know Your
    Triggers' could just as easily be prose, and deleting real content is
    far worse than leaving a duplicated heading.

    Elements are consumed whole, never split, so a heading running into a
    paragraph via `<br>` can't take the paragraph's first sentence with it.

    Structural labels get one allowance, because the TOC and the body
    routinely spell the same label differently ('1. Capitalism' vs
    'CHAPTER 1' + 'Capitalism'): a *leading, label-only* element may be
    consumed without contributing to the match, and a leading label may be
    dropped from the title. Everything after that must still reconstruct
    the title exactly, so the allowance can never cause a partial removal.
    """
    target = _normalize_for_match(title)
    if not target:
        return
    # Try the title as-is first, then without its own leading label.
    candidates = [target]
    bare = _TITLE_LABEL_PREFIX.sub("", target)
    if bare and bare != target:
        candidates.append(bare)
    for cand in candidates:
        consumed = _match_leading_heading(_content_root(soup), cand)
        if consumed:
            for el in consumed:
                el.decompose()
            return


def _match_leading_heading(root, target: str) -> list:
    """Leading elements of *root* that together reconstruct *target*, or
    [] if they don't. Returning [] on anything short of a complete match is
    what makes this safe to delete: 'CHAPTER 3' alone under the title
    'Chapter 3 Know Your Triggers' could just as easily be prose."""
    acc = ""
    consumed = []
    for child in root.find_all(recursive=False):
        chunk = _normalize_for_match(child.get_text())
        if not chunk:
            # Decorative <img>/<br>/empty <p> between heading parts: skip
            # without consuming, so a chapter illustration survives.
            continue
        if not target.startswith(acc + chunk):
            # A leading label the title renders differently ('CHAPTER 1'
            # for '1.'): consume it, but require the rest to match anyway.
            if not acc and _LABEL_ONLY.match(chunk):
                consumed.append(child)
                continue
            return []
        acc += chunk
        consumed.append(child)
        if acc == target:
            return consumed
    return []


def _mark_separator_lines(text: str) -> str:
    """Replace separator-only lines ('* * *', '⁂', '———') with SCENE_BREAK."""
    out = []
    for line in text.split("\n"):
        out.append(SCENE_BREAK if _SEPARATOR_LINE.match(line) else line)
    return "\n".join(out)


def _spine_documents(book: epub.EpubBook) -> list:
    """The book's documents in spine (reading) order. The OPF manifest is an
    unordered inventory — some publishers list front matter after the body —
    so iterating get_items() directly can misorder chapters. Falls back to
    manifest order when the spine is empty or none of its idrefs resolve."""
    docs = []
    for entry in book.spine:
        idref = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            docs.append(item)
    if docs:
        return docs
    return [i for i in book.get_items()
            if i.get_type() == ebooklib.ITEM_DOCUMENT]


def extract_chapters(path: str, preview_chars: int = 50,
                     mark_scene_breaks: bool = False) -> list[Chapter]:
    """Read *path* and return its chapters in spine (reading) order.

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
    for item in _spine_documents(book):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Before ANY get_text: inline markup otherwise splits sentences
        # and words across lines. Doing it once here keeps the length
        # filter, the title, and the marked text consistent with each
        # other — flattening per-read would let them disagree and break
        # the app/worker index parity selected_chapters relies on.
        _flatten_inline(soup)
        # Filter and title use text/soup without the scene-break sentinel
        # ("unmarked"): the app extracts without marking, and inclusion/
        # index/title parity between the two reads is what keeps
        # selected_chapters aligned (module docstring). Flattening above
        # has already run identically for both reads; inserting the
        # sentinel first, by contrast, would let it leak into a
        # preview-fallback title.
        text = soup.get_text(separator="\n").strip()
        if len(text) > MIN_CHAPTER_CHARS:
            title, source = _resolve_title(
                item.get_name(), soup, toc_map, preview_chars
            )
            # Drop the chapter's own heading so it can't reach the LLM and
            # be echoed back under the title the worker already prepends.
            # After the length filter (a heading-heavy short chapter must
            # not drop out and shift every selected_chapters index) and
            # before the scene-break branch (both reads must see the same
            # stripped body, or the app/worker index parity breaks).
            if source in ("toc", "heading"):
                _strip_title_heading(soup, title)
                text = soup.get_text(separator="\n").strip()
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
    """Filter *chapters* to those whose .index is in *indices*, returned in
    the order the indices are listed — the wizard's custom processing order.
    (app.py passes sorted indices, so its runs keep document order.)
    Unknown indices are ignored. `indices is None` means 'all chapters,
    document order'."""
    if indices is None:
        return chapters
    by_index = {c.index: c for c in chapters}
    return [by_index[i] for i in indices if i in by_index]
