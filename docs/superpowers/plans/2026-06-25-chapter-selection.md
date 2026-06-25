# Chapter Selection + Per-Chapter Txt Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick which EPUB chapters get processed, and write each chapter's result to a per-chapter `.txt` file as it finishes (in addition to the existing assembled output).

**Architecture:** Extract chapters in one shared, pure module (`epub_io.py`) used by both the UI (`app.py`, to build a checkbox list) and the pipeline (`worker.py`, to process). The UI passes the selected chapter **indices** through the config dict; the worker filters by them. A new reusable `ChapterListWidget` renders the scrollable checkbox list. Per-chapter txt files reuse the same chapter-block formatter as the assembled output (no duplication).

**Tech Stack:** Python 3.13, PyQt6, ebooklib, BeautifulSoup4, pytest.

## Global Constraints

- Max line length 100; `E221` (aligned assignments) suppressed. Run `pycodestyle --statistics *.py`.
- **No code duplication** — the chapter-block formatter and the chapter title source each have exactly one implementation.
- `epub_io.py` imports `ebooklib`/`bs4` only — never Qt, `app`, `worker`, or `settings`.
- `ProcessingWorker` must never import Qt UI classes.
- `widgets.py` imports `settings` only (plus Qt) — never `app`, `worker`, or `epub_io`.
- All colours come from `bookweaver.json` via `settings.py`.
- Chapter extraction is implemented **only** in `epub_io.extract_chapters`. Positional chapter indices are stable between the app-side and worker-side reads *only because* both go through this one function. Do not reimplement extraction anywhere.
- After any edit touching a class boundary, run `grep -n "^class " *.py`.
- Tests: no Qt install needed (`conftest.py` stubs PyQt6). Widget/app behavior is verified with `QT_QPA_PLATFORM=offscreen` smoke scripts. Run all commands with the project venv: `.venv/bin/python`, `.venv/bin/pytest`.

---

### Task 1: `epub_io.py` — shared chapter extraction

**Files:**
- Create: `epub_io.py`
- Test: `tests/test_epub_io.py`

**Interfaces:**
- Consumes: `ebooklib`, `ebooklib.epub`, `bs4.BeautifulSoup`.
- Produces:
  - `Chapter` frozen dataclass: `index: int`, `doc_name: str`, `title: str`, `text: str`.
  - `extract_chapters(path: str, preview_chars: int = 50) -> list[Chapter]`
  - `select_chapters(chapters: list[Chapter], indices: Iterable[int] | None) -> list[Chapter]`
  - helpers `_flatten_toc(toc) -> dict[str, str]`, `_resolve_title(doc_name, soup, toc_map, preview_chars) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_epub_io.py`:

```python
"""
tests/test_epub_io.py
---------------------
Unit tests for epub_io: TOC flattening, title resolution, end-to-end
chapter extraction against a built EPUB fixture, and index-based selection.
"""
from bs4 import BeautifulSoup
from ebooklib import epub

import epub_io
from epub_io import Chapter, extract_chapters, select_chapters


def _build_epub(tmp_path, docs, toc=None):
    """docs: list of (file_name, html). Returns the written .epub path."""
    book = epub.EpubBook()
    book.set_identifier("id123")
    book.set_title("Fixture Book")
    book.set_language("en")
    items = []
    for name, html in docs:
        it = epub.EpubHtml(title=name, file_name=name, lang="en")
        it.content = html
        book.add_item(it)
        items.append(it)
    book.toc = toc if toc is not None else tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    out = tmp_path / "fixture.epub"
    epub.write_epub(str(out), book)
    return str(out)


BODY = "<p>" + ("word " * 80) + "</p>"  # > 200 chars of text


class TestFlattenToc:
    def test_maps_basename_to_title(self):
        toc = (epub.Link("chap_01.xhtml", "The Beginning", "c1"),)
        assert epub_io._flatten_toc(toc)["chap_01.xhtml"] == "The Beginning"

    def test_strips_anchor_and_path(self):
        toc = (epub.Link("text/chap_01.xhtml#frag", "Anchored", "c1"),)
        assert epub_io._flatten_toc(toc)["chap_01.xhtml"] == "Anchored"

    def test_walks_nested_sections(self):
        nested = ((epub.Section("Part I"),
                   (epub.Link("chap_02.xhtml", "Deep Title", "c2"),)),)
        assert epub_io._flatten_toc(nested)["chap_02.xhtml"] == "Deep Title"


class TestResolveTitle:
    def test_prefers_toc(self):
        soup = BeautifulSoup("<h1>Heading</h1>", "html.parser")
        title = epub_io._resolve_title(
            "chap_01.xhtml", soup, {"chap_01.xhtml": "TOC Title"}, 50
        )
        assert title == "TOC Title"

    def test_falls_back_to_heading(self):
        soup = BeautifulSoup("<h2>My Heading</h2><p>body</p>", "html.parser")
        assert epub_io._resolve_title("x.xhtml", soup, {}, 50) == "My Heading"

    def test_falls_back_to_text_preview(self):
        soup = BeautifulSoup("<p>Once upon a midnight dreary</p>", "html.parser")
        assert epub_io._resolve_title("x.xhtml", soup, {}, 10) == "Once upon"


class TestExtractChapters:
    def test_extracts_and_indexes_contiguously(self, tmp_path):
        path = _build_epub(tmp_path, [
            ("chap_01.xhtml", f"<h1>One</h1>{BODY}"),
            ("chap_02.xhtml", f"<h1>Two</h1>{BODY}"),
        ])
        chapters = extract_chapters(path)
        assert [c.index for c in chapters] == [0, 1]
        assert [c.title for c in chapters] == ["One", "Two"]

    def test_skips_tiny_documents(self, tmp_path):
        path = _build_epub(tmp_path, [
            ("cover.xhtml", "<p>x</p>"),                 # < 200 chars → skipped
            ("chap_01.xhtml", f"<h1>Real</h1>{BODY}"),
        ])
        chapters = extract_chapters(path)
        assert len(chapters) == 1
        assert chapters[0].title == "Real"
        assert chapters[0].index == 0

    def test_uses_toc_title_when_present(self, tmp_path):
        toc = (epub.Link("chap_01.xhtml", "Chapter From TOC", "c1"),)
        path = _build_epub(
            tmp_path, [("chap_01.xhtml", f"<h1>Heading</h1>{BODY}")], toc=toc
        )
        assert extract_chapters(path)[0].title == "Chapter From TOC"


class TestSelectChapters:
    CH = [Chapter(i, f"c{i}.xhtml", f"T{i}", "body") for i in range(4)]

    def test_none_returns_all(self):
        assert select_chapters(self.CH, None) == self.CH

    def test_filters_and_preserves_order(self):
        out = select_chapters(self.CH, [2, 0])
        assert [c.index for c in out] == [0, 2]

    def test_ignores_unknown_indices(self):
        out = select_chapters(self.CH, [1, 99])
        assert [c.index for c in out] == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_epub_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'epub_io'`

- [ ] **Step 3: Create `epub_io.py`**

```python
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

from collections.abc import Iterable
from dataclasses import dataclass

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# A document with more than this many characters of text is a chapter;
# shorter documents (cover, nav) are skipped. The checkbox list lets the
# user deselect anything that slips past this heuristic.
MIN_CHAPTER_CHARS = 200


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


def extract_chapters(path: str, preview_chars: int = 50) -> list[Chapter]:
    """Read *path* and return its chapters in document order."""
    book = epub.read_epub(path)
    toc_map = _flatten_toc(book.toc)
    chapters: list[Chapter] = []
    idx = 0
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n").strip()
        if len(text) > MIN_CHAPTER_CHARS:
            title = _resolve_title(item.get_name(), soup, toc_map, preview_chars)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_epub_io.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "feat: add shared epub_io chapter extraction module"
```

---

### Task 2: `chapter_title_preview_chars` config key

**Files:**
- Modify: `settings.py` (the `SETTINGS = {…}` block inside `_build`, ~line 242-247)
- Modify: `bookweaver.json` (add top-level key)
- Test: `tests/test_settings.py` (add a class)

**Interfaces:**
- Produces: `SETTINGS["chapter_title_preview_chars"]: int` (default 50).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py` (the helpers `_write_json` / `MINIMAL_CFG` and `_build`, `settings_module` already exist in this file):

```python
class TestChapterTitlePreviewChars:
    def test_defaults_to_50_when_missing(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert settings_module.SETTINGS["chapter_title_preview_chars"] == 50
        _build()  # restore

    def test_reads_value_from_config(self, tmp_path):
        cfg = dict(MINIMAL_CFG)
        cfg["chapter_title_preview_chars"] = 80
        p = _write_json(tmp_path, cfg)
        _build(p)
        assert settings_module.SETTINGS["chapter_title_preview_chars"] == 80
        _build()  # restore
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py::TestChapterTitlePreviewChars -v`
Expected: FAIL — `KeyError: 'chapter_title_preview_chars'`

- [ ] **Step 3: Add the key in `settings.py`**

In `_build`, extend the `SETTINGS` dict:

```python
    SETTINGS = {
        "models":        cfg["models"],
        "default_model": cfg["default_model"],
        "voices":        cfg.get("voices", {}),
        "tts":           cfg.get("tts", {}),
        "chapter_title_preview_chars": int(
            cfg.get("chapter_title_preview_chars", 50)
        ),
    }
```

- [ ] **Step 4: Add the key in `bookweaver.json`**

Add a top-level key (place it near `ollama_timeout`):

```json
  "chapter_title_preview_chars": 50,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_settings.py::TestChapterTitlePreviewChars -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add settings.py bookweaver.json tests/test_settings.py
git commit -m "feat: add configurable chapter_title_preview_chars setting"
```

---

### Task 3: `_chapter_block` formatter + refactor `_write_txt`

**Files:**
- Modify: `worker.py` (`_write_txt`, ~line 358-377; add `_chapter_block` static method)
- Test: `tests/test_worker.py` (add a class; existing `TestWriteTxt` must still pass)

**Interfaces:**
- Produces: `ProcessingWorker._chapter_block(title: str, body: str) -> str` (static).
- This is a pure refactor — `_write_txt` output is byte-for-byte unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_worker.py`:

```python
class TestChapterBlock:
    def test_block_matches_legacy_format(self):
        block = ProcessingWorker._chapter_block("Capítulo 1", "Hola mundo.")
        assert block == f"\n{'=' * 60}\nCapítulo 1\n{'=' * 60}\n\nHola mundo.\n\n"

    def test_title_and_body_present(self):
        block = ProcessingWorker._chapter_block("My Title", "Some body text")
        assert "My Title" in block
        assert "Some body text" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_worker.py::TestChapterBlock -v`
Expected: FAIL — `AttributeError: ... has no attribute '_chapter_block'`

- [ ] **Step 3: Add the helper and use it in `_write_txt`**

Add the static method (place it just above `_write_txt`):

```python
    @staticmethod
    def _chapter_block(title: str, body: str) -> str:
        """The shared `===`-delimited chapter block used by both the
        assembled .txt output and the per-chapter .txt files."""
        return f"\n{'=' * 60}\n{title}\n{'=' * 60}\n\n{body}\n\n"
```

Replace the loop body in `_write_txt`:

```python
            for title, body in results:
                fh.write(f"\n{'=' * 60}\n{title}\n{'=' * 60}\n\n{body}\n\n")
```

with:

```python
            for title, body in results:
                fh.write(self._chapter_block(title, body))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_worker.py::TestChapterBlock tests/test_worker.py::TestWriteTxt -v`
Expected: PASS (new block tests + all existing `_write_txt` tests still green)

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "refactor: extract shared _chapter_block formatter in worker"
```

---

### Task 4: per-chapter file writer

**Files:**
- Modify: `worker.py` (add `_safe_filename` static + `_write_chapter_file` method, near the other output writers)
- Test: `tests/test_worker.py` (add a class)

**Interfaces:**
- Consumes: `ProcessingWorker._chapter_block` (Task 3).
- Produces:
  - `ProcessingWorker._safe_filename(title: str) -> str` (static) — filesystem-safe, whitespace-collapsed, length-capped.
  - `ProcessingWorker._write_chapter_file(out_folder: Path, stem: str, level: str, index: int, title: str, body: str) -> Path` — writes `{stem}_ES_{level}_chapters/{index+1:02d} - {safe_title}.txt`, creating the subfolder.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_worker.py`:

```python
class TestSafeFilename:
    def test_replaces_path_separators(self):
        assert "/" not in ProcessingWorker._safe_filename("a/b")
        assert "\\" not in ProcessingWorker._safe_filename("a\\b")

    def test_collapses_whitespace(self):
        assert ProcessingWorker._safe_filename("a   b\tc") == "a b c"

    def test_caps_length(self):
        assert len(ProcessingWorker._safe_filename("x" * 200)) <= 80

    def test_empty_falls_back(self):
        assert ProcessingWorker._safe_filename("   ") == "untitled"


class TestWriteChapterFile:
    def test_creates_subfolder_and_numbered_file(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "mybook", "B2", 2, "The Title", "Body.")
        assert out.parent.name == "mybook_ES_B2_chapters"
        assert out.name == "03 - The Title.txt"
        assert out.exists()

    def test_file_contains_block(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "b", "B2", 0, "T", "Hello body")
        text = out.read_text(encoding="utf-8")
        assert "T" in text and "Hello body" in text

    def test_index_zero_is_one_padded(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "b", "B2", 0, "First", "x")
        assert out.name.startswith("01 - ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_worker.py::TestSafeFilename tests/test_worker.py::TestWriteChapterFile -v`
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Implement the writer**

Add `import re` at the top of `worker.py` if not present. Add these methods near the other output writers:

```python
    @staticmethod
    def _safe_filename(title: str) -> str:
        """Make *title* safe for a filename: strip illegal characters,
        collapse whitespace, cap length. Falls back to 'untitled'."""
        cleaned = re.sub(r'[/\\:*?"<>|]', "", title)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:80].strip() or "untitled"

    def _write_chapter_file(
        self,
        out_folder: Path,
        stem: str,
        level: str,
        index: int,
        title: str,
        body: str,
    ) -> Path:
        """Write a single chapter's result to
        {stem}_ES_{level}_chapters/{NN} - {title}.txt and return the path.
        NN = index + 1, matching the number shown in the UI chapter list."""
        chapters_dir = out_folder / f"{stem}_ES_{level}_chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{index + 1:02d} - {self._safe_filename(title)}.txt"
        out_path = chapters_dir / fname
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(self._chapter_block(title, body))
        self.log.emit(f"   ↳ Saved chapter file → {out_path.name}", "muted")
        return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_worker.py::TestSafeFilename tests/test_worker.py::TestWriteChapterFile -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: add per-chapter txt file writer"
```

---

### Task 5: integrate extraction, selection, and per-chapter output into `worker.run`

**Files:**
- Modify: `worker.py` (`run`: imports ~60-65, cfg parse ~76-95, extraction ~106-121, loop header ~138, per-chapter write after ~257, out_formats hoist)
- Modify: `tests/test_worker.py` (`_make_worker` fixture: drop `first_only`)

**Interfaces:**
- Consumes: `epub_io.extract_chapters`, `epub_io.select_chapters` (Task 1); `_write_chapter_file` (Task 4); `SETTINGS` (already imported in `worker.py`).
- The chapter loop iterates `Chapter` objects: `chapter.index` (original list position, used for per-chapter filename) vs the loop's `idx` (position in the *filtered* list, used for progress/resume).

- [ ] **Step 1: Update the `_make_worker` fixture**

In `tests/test_worker.py`, remove the `"first_only": True,` line from the default config dict in `_make_worker` (worker no longer reads it). The fixture needs no `selected_chapters` key — `cfg.get("selected_chapters")` defaults to `None` = all chapters.

- [ ] **Step 2: Remove the `first_only` read**

In `run()`, delete this line (~80):

```python
        first_only = cfg["first_only"]
```

- [ ] **Step 3: Add the lazy `epub_io` import**

In `run()`'s top import block (the `try:` at ~61-65), add `epub_io`:

```python
        try:
            import ebooklib
            from ebooklib import epub as ebooklib_epub
            import httpx
            from bs4 import BeautifulSoup
            import epub_io
        except ImportError as exc:
```

(`ebooklib`/`BeautifulSoup` remain imported here — `_write_epub` still uses `ebooklib_epub`.)

- [ ] **Step 4: Replace the extraction + first_only block**

Replace this block (~106-121):

```python
        chapters = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()
                if len(text) > 200:  # skip tiny nav/cover pages
                    chapters.append((item.get_name(), text))

        if not chapters:
            self.log.emit("No readable chapters found in EPUB.", "error")
            self.finished.emit(False, "")
            return

        if first_only:
            chapters = chapters[:1]
            self.log.emit("ℹ️   Processing first chapter only.", "info")
```

with:

```python
        preview_chars = SETTINGS.get("chapter_title_preview_chars", 50)
        all_chapters = epub_io.extract_chapters(epub_path, preview_chars)
        if not all_chapters:
            self.log.emit("No readable chapters found in EPUB.", "error")
            self.finished.emit(False, "")
            return

        chapters = epub_io.select_chapters(
            all_chapters, cfg.get("selected_chapters")
        )
        if not chapters:
            self.log.emit("No chapters selected to process.", "error")
            self.finished.emit(False, "")
            return
        if len(chapters) < len(all_chapters):
            self.log.emit(
                f"ℹ️   Processing {len(chapters)} of "
                f"{len(all_chapters)} chapters.", "info"
            )
```

Note: the existing `book = ebooklib_epub.read_epub(epub_path)` call (~100) and its surrounding `try/except` log "Loading…"/"Failed to open EPUB" — leave them; `book` is still used by EPUB output metadata? Check: `book` is only used for the old extraction. If `book` becomes unused after this change, remove the `book = ...read_epub(...)` line and its try/except (lines ~98-104) too, and keep the `📖 Loading` log line as a plain `self.log.emit`. Verify with `grep -n "\bbook\b" worker.py` after editing; if `book` has no other use, delete the now-dead load. (`extract_chapters` opens the EPUB itself.)

- [ ] **Step 5: Iterate `Chapter` objects in the loop**

Change the loop header (~138):

```python
        for idx, (_name, text) in enumerate(chapters):
```

to:

```python
        for idx, chapter in enumerate(chapters):
            text = chapter.text
```

(`text` is referenced by `_split_into_chunks(text, …)` just below — keep that working. `idx` remains the filtered-list position used everywhere for progress/resume/logs.)

- [ ] **Step 6: Hoist `out_formats` above the loop**

The per-chapter writer needs `out_formats` inside the loop. Move this computation (currently ~265, after the loop):

```python
        out_formats = out_format if isinstance(out_format, list) else [out_format]
```

to **before** the `for idx, chapter in enumerate(chapters):` loop (e.g. just after `steps_per_chapter`/`total_steps` are set, ~124). Also move `stem = Path(epub_path).stem` (currently ~263) to the same spot so it is available inside the loop. Remove the now-duplicate assignments from their old location in the `# ── write output ──` section.

- [ ] **Step 7: Write the per-chapter file after each chapter completes**

After this block (~256-259):

```python
            ch_title = f"Chapter {idx + 1}" if mode == "summarise_only" else f"Capítulo {idx + 1}"
            results.append((ch_title, "\n\n".join(spanish_parts)))
            self.completed_results = results[:]
            self.log.emit(f"✅  Chapter {idx + 1} done.", "success")
```

insert:

```python
            if "txt" in out_formats:
                self._write_chapter_file(
                    out_folder, stem, level,
                    chapter.index, chapter.title,
                    "\n\n".join(spanish_parts),
                )
```

(`out_folder` is a `Path` already; `_write_chapter_file` creates the subfolder via `parents=True`, so it is safe even before the assembled-output `out_folder.mkdir` at the write step.)

- [ ] **Step 8: Run the full worker test suite + class check**

Run: `.venv/bin/pytest tests/test_worker.py -v`
Expected: PASS (the one pre-existing `test_settings` timeout failure is unrelated and not in this file).

Run: `grep -n "^class " *.py`
Expected: includes `worker.py:  class ProcessingWorker(QThread)` and `epub_io.py: class Chapter` (dataclass — it is `@dataclass class Chapter:`, so it will show as `class Chapter`). Confirm `ProcessingWorker` is intact.

Run: `grep -n "first_only" worker.py`
Expected: no matches.

- [ ] **Step 9: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: process only selected chapters and write per-chapter txt files"
```

---

### Task 6: `ChapterListWidget` reusable widget

**Files:**
- Modify: `widgets.py` (add class + Qt imports it needs)
- Test: smoke script run with `QT_QPA_PLATFORM=offscreen` (Qt widgets are not part of the pytest suite — `conftest.py` stubs PyQt6).

**Interfaces:**
- Produces `ChapterListWidget(QWidget)`:
  - `set_chapters(pairs: list[tuple[int, str]]) -> None` — `(index, label)`; rebuilds the list, all checked, Select-All checked.
  - `selected_indices() -> list[int]` — sorted list of checked indices.
  - `clear() -> None` — remove all rows (called when a new book loads or selection fails).
- Stays decoupled from `epub_io` — operates on `(index, label)` only.

- [ ] **Step 1: Add the widget to `widgets.py`**

Ensure these names are imported at the top of `widgets.py` (add any missing to the existing `from PyQt6.QtWidgets import (...)` / `from PyQt6.QtCore import (...)` blocks): `QCheckBox`, `QScrollArea`, `QVBoxLayout`, `QWidget`, `QHBoxLayout` (most already present — verify). Then append:

```python
# ──────────────────────────────────────────────────────────────
#  CHAPTER LIST WIDGET
# ──────────────────────────────────────────────────────────────
class ChapterListWidget(QWidget):
    """A scrollable list of chapter checkboxes with a 'Select all' master
    checkbox. Generic: it knows only (index, label) pairs, never the EPUB.

    Use set_chapters() to (re)populate, selected_indices() to read the
    selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._select_all = QCheckBox("Select all")
        self._select_all.setTristate(True)
        self._select_all.clicked.connect(self._on_select_all_clicked)
        layout.addWidget(self._select_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(140)
        scroll.setMaximumHeight(260)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 4, 8, 4)
        self._inner_layout.setSpacing(2)
        self._inner_layout.addStretch()
        scroll.setWidget(self._inner)
        layout.addWidget(scroll)

        # index -> QCheckBox
        self._boxes: dict[int, QCheckBox] = {}

    def clear(self) -> None:
        for box in self._boxes.values():
            self._inner_layout.removeWidget(box)
            box.deleteLater()
        self._boxes = {}
        self._refresh_select_all()

    def set_chapters(self, pairs: list[tuple[int, str]]) -> None:
        """Replace the list. All chapters start checked."""
        self.clear()
        # insert before the trailing stretch (last item)
        insert_at = self._inner_layout.count() - 1
        for index, label in pairs:
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._refresh_select_all)
            self._inner_layout.insertWidget(insert_at, box)
            insert_at += 1
            self._boxes[index] = box
        self._refresh_select_all()

    def selected_indices(self) -> list[int]:
        return sorted(i for i, b in self._boxes.items() if b.isChecked())

    def _on_select_all_clicked(self) -> None:
        # On click, drive every child to the master's new checked state.
        target = self._select_all.checkState() != Qt.CheckState.Unchecked
        for box in self._boxes.values():
            box.blockSignals(True)
            box.setChecked(target)
            box.blockSignals(False)
        self._refresh_select_all()

    def _refresh_select_all(self) -> None:
        total = len(self._boxes)
        checked = sum(1 for b in self._boxes.values() if b.isChecked())
        self._select_all.blockSignals(True)
        if total == 0 or checked == 0:
            self._select_all.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total:
            self._select_all.setCheckState(Qt.CheckState.Checked)
        else:
            self._select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        self._select_all.blockSignals(False)
```

(`Qt` is already imported in `widgets.py` via `from PyQt6.QtCore import Qt, pyqtSignal`.)

- [ ] **Step 2: Write and run the offscreen smoke test**

Create `scratchpad` smoke at `/private/tmp/claude-501/-Users-jan-Projects-bookweaver/15e49adc-29aa-4039-869a-6d15046bb21a/scratchpad/smoke_chapterlist.py`:

```python
from PyQt6.QtWidgets import QApplication
from widgets import ChapterListWidget

app = QApplication([])
w = ChapterListWidget()
w.set_chapters([(0, "01. One"), (1, "02. Two"), (2, "03. Three")])
assert w.selected_indices() == [0, 1, 2], w.selected_indices()

# uncheck the middle box
w._boxes[1].setChecked(False)
assert w.selected_indices() == [0, 2], w.selected_indices()

# select-all click re-checks everything
w._select_all.setChecked(True)
w._on_select_all_clicked()
assert w.selected_indices() == [0, 1, 2], w.selected_indices()

# clear empties it
w.clear()
assert w.selected_indices() == []
print("ChapterListWidget smoke OK")
```

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python /private/tmp/claude-501/-Users-jan-Projects-bookweaver/15e49adc-29aa-4039-869a-6d15046bb21a/scratchpad/smoke_chapterlist.py`
Expected: prints `ChapterListWidget smoke OK` and exits 0.

- [ ] **Step 3: Class check**

Run: `grep -n "^class " widgets.py`
Expected: existing classes plus `widgets.py: class ChapterListWidget(QWidget)`.

- [ ] **Step 4: Commit**

```bash
git add widgets.py
git commit -m "feat: add reusable ChapterListWidget"
```

---

### Task 7: wire chapter selection into `app.py`

**Files:**
- Modify: `app.py` (imports; `_add_source_group` or a new `_add_chapters_group`; `_on_epub_selected` ~451; `_add_options_group` ~274-278 remove first_only; `_build_config` ~470-511)

**Interfaces:**
- Consumes: `epub_io.extract_chapters` (lazy import), `ChapterListWidget` (Task 6), `SETTINGS` (already imported).
- Produces config key `"selected_chapters": list[int]`; removes `"first_only"`.
- Resume note: `_on_resume` spreads `**self._resume_state["config"]` (the original worker config), so `selected_chapters` is re-applied on resume automatically — **no resume code change needed.**

- [ ] **Step 1: Import the widget**

In the `from widgets import (…)` block, add `ChapterListWidget`:

```python
from widgets import (
    ChapterListWidget,
    CreativitySlider,
    FilePickerRow,
    FolderPickerRow,
    LogWidget,
    ProgressBar,
    SummarizationSlider,
)
```

- [ ] **Step 2: Add a Chapters group and call it from `_build_ui`**

In the method that adds groups (where `_add_source_group(form)` is called, ~103), add a call right after it:

```python
        self._add_source_group(form)
        self._add_chapters_group(form)
```

Add the method (next to `_add_source_group`):

```python
    def _add_chapters_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Chapters")
        cl = QVBoxLayout(grp)
        cl.addWidget(QLabel("Select chapters to process:"))
        self._chapter_list = ChapterListWidget()
        cl.addWidget(self._chapter_list)
        self._chapters: list = []  # list[epub_io.Chapter]; filled on selection
        form.addWidget(grp)
```

- [ ] **Step 3: Populate the list on EPUB selection**

In `_on_epub_selected` (~451), after the metadata `try/except` block and before/after the out-folder default, add:

```python
        # Build the chapter selection list.
        try:
            import epub_io
            preview_chars = SETTINGS.get("chapter_title_preview_chars", 50)
            self._chapters = epub_io.extract_chapters(path, preview_chars)
            self._chapter_list.set_chapters(
                [(c.index, f"{c.index + 1:02d}. {c.title}") for c in self._chapters]
            )
        except Exception as exc:
            self._chapters = []
            self._chapter_list.clear()
            self.statusBar().showMessage(
                f"Could not read chapters: {exc}", 5000
            )
```

- [ ] **Step 4: Remove the `first_only` checkbox**

In `_add_options_group` (~274-278), delete:

```python
        self._first_only_chk = QCheckBox(
            "Process first chapter only  (preview / quick test)"
        )
        self._first_only_chk.setChecked(True)
        ol.addWidget(self._first_only_chk)
```

(Verify the exact current label text in the file before deleting; remove the whole widget creation + `addWidget`.)

- [ ] **Step 5: Update `_build_config`**

In `_build_config`, after the existing `out_fmt` validation, add a selection check, and edit the returned dict:

```python
        selected = self._chapter_list.selected_indices()
        if not selected:
            self._log.append_line(
                "Please select at least one chapter to process.", "warning"
            )
            return None
```

In the returned dict, **remove** the line:

```python
            "first_only": self._first_only_chk.isChecked(),
```

and **add**:

```python
            "selected_chapters": selected,
```

- [ ] **Step 6: Offscreen smoke test of the app wiring**

Build a tiny EPUB and drive the app headless. Create
`/private/tmp/claude-501/-Users-jan-Projects-bookweaver/15e49adc-29aa-4039-869a-6d15046bb21a/scratchpad/smoke_app_chapters.py`:

```python
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from ebooklib import epub
from PyQt6.QtWidgets import QApplication

BODY = "<p>" + ("word " * 80) + "</p>"

def build_epub(path):
    book = epub.EpubBook()
    book.set_identifier("id1"); book.set_title("T"); book.set_language("en")
    items = []
    for name, h in [("c1.xhtml", f"<h1>One</h1>{BODY}"),
                    ("c2.xhtml", f"<h1>Two</h1>{BODY}"),
                    ("c3.xhtml", f"<h1>Three</h1>{BODY}")]:
        it = epub.EpubHtml(title=name, file_name=name, lang="en")
        it.content = h; book.add_item(it); items.append(it)
    book.toc = tuple(items)
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    epub.write_epub(path, book)

app = QApplication([])
import app as appmod
w = appmod.BookWeaverApp()
p = "/tmp/smoke_book.epub"; build_epub(p)
w._file_picker._edit.setText(p)
w._on_epub_selected(p)
assert len(w._chapters) == 3, len(w._chapters)
assert w._chapter_list.selected_indices() == [0, 1, 2]

# deselect chapter 2 (index 1), confirm config reflects it
w._chapter_list._boxes[1].setChecked(False)
cfg = w._build_config()
assert cfg is not None
assert cfg["selected_chapters"] == [0, 2], cfg["selected_chapters"]
assert "first_only" not in cfg
print("app chapter-selection smoke OK")
```

Run: `.venv/bin/python /private/tmp/claude-501/-Users-jan-Projects-bookweaver/15e49adc-29aa-4039-869a-6d15046bb21a/scratchpad/smoke_app_chapters.py`
Expected: prints `app chapter-selection smoke OK`. (If `_build_config` returns `None` due to no output folder, the smoke sets the file path whose parent becomes the default out folder — `/tmp` — so it should pass. If it still returns None, set `w._out_folder.set_path("/tmp")` before `_build_config`.)

- [ ] **Step 7: Class check + grep**

Run: `grep -n "^class " *.py` (confirm `app.py: class BookWeaverApp(QMainWindow)` intact)
Run: `grep -n "first_only" app.py` → expected: no matches.

- [ ] **Step 8: Commit**

```bash
git add app.py
git commit -m "feat: chapter selection UI wired into config; remove first_only"
```

---

### Task 8: documentation + full verification

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none (docs + verification only).

- [ ] **Step 1: Update `CLAUDE.md`**

Make these edits (match the existing wording/format):

1. **File map table** — add a row:
   `| `epub_io.py` | EPUB → ordered Chapter list (titles via TOC→heading→preview); shared by app & worker | For chapter extraction/title logic |`
   and update the `worker.py` row note to say it no longer extracts chapters inline.

2. **Architecture rule 1 (import graph)** — add:
   - `app` → `epub_io` (lazy, in `_on_epub_selected`)
   - `worker` → `epub_io` (lazy, inside `run`)
   - `epub_io` → `ebooklib`/`bs4` only; never Qt, `app`, `worker`, or `settings`
   - note `widgets` → `settings` only (ChapterListWidget stays decoupled from `epub_io`)

3. **Configuration system** — add `chapter_title_preview_chars` (default 50) to the list of `bookweaver.json` keys.

4. **Pipeline config-keys table** — remove the `first_only` row (the control is gone); add:
   `| `selected_chapters` | `list[int]` | Indices (into the extracted chapter list) the user ticked; the worker processes only these |`

5. **Pipeline → Per chapter** — note that after a chapter completes, if `"txt"` is in `out_format`, its result is also written to `{stem}_ES_{level}_chapters/{NN} - {title}.txt` (all modes). Mention the shared `_chapter_block` formatter.

6. **Resume system** — note that `selected_chapters` rides along in the resume config automatically (the `_on_resume` `**config` spread), so resumed runs process the same subset.

7. **Known historical issues / class check** — add `epub_io.py: class Chapter` to the expected `grep -n "^class "` output, and `widgets.py: class ChapterListWidget(QWidget)`.

- [ ] **Step 2: Full test suite**

Run: `.venv/bin/pytest -q`
Expected: all pass **except** the one documented pre-existing failure `test_settings.py::TestOllamaTimeout::test_defaults_when_missing` (asserts 600, code defaults to 1200 — unrelated to this work).

- [ ] **Step 3: Lint**

Run: `.venv/bin/pycodestyle --statistics --max-line-length=100 epub_io.py worker.py app.py widgets.py settings.py`
Expected: no new violations (E221 is intentionally suppressed project-wide; if it appears, it is acceptable per project policy).

- [ ] **Step 4: Class boundary check**

Run: `grep -n "^class " *.py`
Expected output includes:
```
app.py:    class BookWeaverApp(QMainWindow)
epub_io.py: class Chapter
widgets.py: class SummarizationSlider(QWidget)
widgets.py: class CreativitySlider(QWidget)
widgets.py: class FilePickerRow(QWidget)
widgets.py: class FolderPickerRow(QWidget)
widgets.py: class LogWidget(QTextEdit)
widgets.py: class ProgressBar(QWidget)
widgets.py: class ChapterListWidget(QWidget)
worker.py:  class ProcessingWorker(QThread)
```

- [ ] **Step 5: Re-run both offscreen smokes**

Run both smoke scripts from Tasks 6 and 7 again; expected `... smoke OK` from each.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document chapter selection and per-chapter output"
```

---

## Self-Review

**Spec coverage:**
- Chapter list on selection with titles/preview → Tasks 1 (titles), 6 (widget), 7 (wiring). ✓
- Configurable preview chars → Task 2. ✓
- Per-chapter checkbox + Select all → Task 6. ✓
- Only selected chapters processed (all modes) → Task 5 (`select_chapters` filter, mode-agnostic loop). ✓
- Keep assembled txt + write per-chapter file when txt selected → Tasks 3 (shared formatter), 4 (writer), 5 (integration, `"txt" in out_formats` guard). ✓
- Replace `first_only` → Tasks 5 (worker), 7 (app). ✓
- No code duplication → single `_chapter_block` (Task 3, reused Task 4); single extraction in `epub_io` (Task 1); title source single (`_resolve_title`). ✓
- Resume threading → Task 7 note (automatic via `**config` spread); verified by `selected_chapters` living in the original config. ✓
- Docs/import-graph → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step has full code; every command has expected output. ✓

**Type consistency:** `Chapter(index, doc_name, title, text)` used consistently; `extract_chapters`/`select_chapters`/`_chapter_block`/`_write_chapter_file`/`_safe_filename` signatures match across tasks; `selected_chapters: list[int]` produced by app (Task 7) and consumed by worker via `cfg.get("selected_chapters")` → `select_chapters` (Task 5). ✓