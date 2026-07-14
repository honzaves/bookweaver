# Chapter Names + User-Defined Processing Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the wizard user reorder chapters (drag-and-drop + per-row ▲▼ buttons); the custom order drives processing and every output (txt/epub/html/MP3), with per-chapter files renumbered to the new order. Pin that EPUB3 nav-only books get real chapter names.

**Architecture:** `selected_chapters` (an existing config key) becomes an *ordered* list: `epub_io.select_chapters` returns chapters in the order the indices are given. The wizard's `TriStateChapterList` is reworked onto QListWidget (drag + ▲▼, live renumbering); row order flows through `WizardState.chapters` → `build_config` unchanged. A new config key `chapter_numbering: "position"` (wizard) vs `"book"` (default, original app) controls per-chapter txt file numbers. Outputs need no changes — they all iterate `results`, which is built in processing order.

**Tech Stack:** Python 3, PyQt6, ebooklib, pytest (conftest stubs PyQt6 — Qt widgets are verified via offscreen scripts, not pytest).

**Spec:** `docs/superpowers/specs/2026-07-14-chapter-order-and-names-design.md`

## Global Constraints

- All colours come from `bookweaver.json` / `wizard_theme.py` — never hardcode hex values (CLAUDE.md rule 2).
- `wizard_logic.py` stays pure and Qt-free; `epub_io.py` imports only ebooklib/bs4 (CLAUDE.md rule 1).
- Max line length 100; lint gate: `pycodestyle --config=.pycodestyle --statistics <files>` must introduce **no new violations**. Every touched file is currently clean EXCEPT `worker.py`, whose accepted baseline is exactly: `728:101 E501` + W503 at `753, 754, 799, 897` (line numbers may shift by edits above them; the count — 1×E501, 4×W503 — must not grow). Never edit `.pycodestyle`.
- After any edit touching a class boundary run `grep -n "^class " *.py` and compare against the CLAUDE.md list (Task 7 updates that list).
- Test suite: `python -m pytest tests/ -q`. Exactly one pre-existing failure is expected and NOT ours: `test_settings.py::TestOllamaTimeout::test_defaults_when_missing`.
- Python environment: uv venv — if anything needs installing use `uv pip install`, never bare `pip`.
- Original `app.py` behaviour must remain byte-identical (it sends sorted indices and never sets `chapter_numbering`).

---

### Task 1: Commit the pending spine-order bugfix

The working tree already contains a reviewed, test-covered bugfix (uncommitted): `extract_chapters` now iterates the spine instead of the manifest. This feature builds on top of it; commit it first so feature commits stay clean. **Do not commit `docs/todo.txt`** (unrelated user edit).

**Files:**
- Commit (already modified): `epub_io.py`, `tests/test_epub_io.py`

**Interfaces:**
- Produces: `epub_io._spine_documents(book) -> list` (docs in spine order, manifest fallback); `extract_chapters` returning chapters in spine order. Later tasks assume this is committed.

- [ ] **Step 1: Verify the tree state and tests**

Run: `git status --short && python -m pytest tests/test_epub_io.py -q`
Expected: `M epub_io.py`, `M tests/test_epub_io.py`, `M docs/todo.txt` (leave alone); all epub_io tests PASS.

- [ ] **Step 2: Commit**

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "fix(epub_io): extract chapters in spine (reading) order, not manifest order

The OPF manifest is an unordered inventory; some publishers list front
matter after the body (books/mattering_too), misordering every output.
Reading order is defined by the spine. Falls back to manifest order when
the spine is empty or unresolvable.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Pin nav-only chapter names + bump ebooklib floor

ebooklib 0.20 already parses the EPUB3 `nav.xhtml` TOC into `book.toc` (verified by probe; nav title wins when both NCX and nav exist). No BookWeaver code change — add a regression test pinning the behaviour and raise the dependency floor so fresh installs get it.

**Files:**
- Modify: `tests/test_epub_io.py` (append a test class)
- Modify: `pyproject.toml:12` (`ebooklib>=0.18` → `ebooklib>=0.20`)
- Modify: `requirements.txt:2` (`ebooklib>=0.18` → `ebooklib>=0.20`)

**Interfaces:**
- Consumes: `extract_chapters(path)` (Task 1's spine ordering: only spine docs are extracted, so the nav doc itself — not in the spine — never appears as a chapter).
- Produces: nothing new — a behaviour pin.

- [ ] **Step 1: Write the pinning test**

Append to `tests/test_epub_io.py` (module already imports `epub` from ebooklib and defines `BODY`):

```python
class TestNavOnlyTitles:
    def test_nav_only_epub_resolves_real_names(self, tmp_path):
        """ebooklib >= 0.20 parses the EPUB3 nav TOC into book.toc, so a
        book with an EMPTY NCX still gets real chapter names through the
        existing TOC -> heading -> preview chain. Pin it: if a future
        ebooklib regresses this, the title would fall back to a text
        preview ('word word word ...') and this test fails."""
        book = epub.EpubBook()
        book.set_identifier("id123")
        book.set_title("Fixture Book")
        book.set_language("en")
        c1 = epub.EpubHtml(file_name="c1.xhtml", lang="en")
        c1.content = BODY                      # no headings, no <title>
        book.add_item(c1)
        nav = epub.EpubHtml(file_name="nav.xhtml", lang="en")
        nav.content = (
            '<nav epub:type="toc"><ol>'
            '<li><a href="c1.xhtml">Real Name</a></li></ol></nav>'
        )
        nav.properties.append("nav")
        book.add_item(nav)
        book.add_item(epub.EpubNcx())          # NCX present but empty
        book.spine = [c1]
        path = tmp_path / "navonly.epub"
        epub.write_epub(str(path), book)

        chapters = extract_chapters(str(path))
        assert [c.title for c in chapters] == ["Real Name"]
```

- [ ] **Step 2: Run it — expected PASS (this is a pin, not TDD red-green)**

Run: `python -m pytest tests/test_epub_io.py::TestNavOnlyTitles -v`
Expected: PASS. If it FAILS, stop — the environment's ebooklib does not parse nav TOCs and the spec amendment's premise is wrong; report back instead of patching.

- [ ] **Step 3: Bump the dependency floor**

In `pyproject.toml` change the line `    "ebooklib>=0.18",` to `    "ebooklib>=0.20",`.
In `requirements.txt` change the line `ebooklib>=0.18` to `ebooklib>=0.20`.

- [ ] **Step 4: Full suite + lint**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics tests/test_epub_io.py`
Expected: only the pre-existing `test_settings` failure; lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_epub_io.py pyproject.toml requirements.txt
git commit -m "test(epub_io): pin nav-only TOC titles; require ebooklib>=0.20

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `select_chapters` honours the given index order

**Files:**
- Modify: `epub_io.py` (`select_chapters`, currently the last function, ~lines 155-162)
- Test: `tests/test_epub_io.py` (`TestSelectChapters`)

**Interfaces:**
- Consumes: `Chapter` dataclass (`.index` is the stable extracted position).
- Produces: `select_chapters(chapters: list[Chapter], indices: Iterable[int] | None) -> list[Chapter]` — returns chapters **in the order the indices are listed**; unknown indices ignored; `None` → all chapters, document order. Task 5's worker behaviour depends on this.

- [ ] **Step 1: Write the failing test**

In `tests/test_epub_io.py`, class `TestSelectChapters`, **replace**:

```python
    def test_filters_and_preserves_order(self):
        out = select_chapters(self.CH, [2, 0])
        assert [c.index for c in out] == [0, 2]
```

**with**:

```python
    def test_returns_chapters_in_given_order(self):
        out = select_chapters(self.CH, [2, 0])
        assert [c.index for c in out] == [2, 0]

    def test_sorted_indices_keep_document_order(self):
        # app.py sends sorted indices; its behaviour must stay identical.
        out = select_chapters(self.CH, [0, 2])
        assert [c.index for c in out] == [0, 2]
```

- [ ] **Step 2: Run to verify the new test fails**

Run: `python -m pytest tests/test_epub_io.py::TestSelectChapters -v`
Expected: `test_returns_chapters_in_given_order` FAILS with `[0, 2] != [2, 0]`; the other two PASS.

- [ ] **Step 3: Implement**

In `epub_io.py`, replace the whole `select_chapters` function with:

```python
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
```

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics epub_io.py tests/test_epub_io.py`
Expected: only the pre-existing `test_settings` failure; lint clean.

- [ ] **Step 5: Commit**

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "feat(epub_io): select_chapters honours the given index order

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `wizard_logic` — `chapter_numbering` key, ordered emission pinned

**Files:**
- Modify: `wizard_logic.py` (CONFIG_KEYS ~line 40-48; `ChapterRow` docstring ~74-83; `build_config` ~212-254)
- Test: `tests/test_wizard_logic.py` (`TestBuildConfig`, ~line 177 on)

**Interfaces:**
- Consumes: `ChapterRow(index, title, checked)`; `WizardState.chapters` list order = display order (Task 6 guarantees this).
- Produces: `build_config(state, backend)` dict now has 23 keys including `"chapter_numbering": "position"` (always, both backends — shape must not branch); `selected_chapters` is the checked rows' `.index` values **in row order**. Task 5 reads `chapter_numbering`; Task 7 documents it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_wizard_logic.py`, class `TestBuildConfig`:

Rename and update the key-count test:

```python
    def test_emits_exactly_the_23_contract_keys(self):
        cfg = wl.build_config(_state(), "mlx")
        assert set(cfg) == wl.CONFIG_KEYS
        assert len(wl.CONFIG_KEYS) == 23
```

In `test_covers_every_key_app_py_emits` change the docstring to
`"""The wizard is a superset of app.py's 21 keys, plus max_tokens and chapter_numbering."""`
and the last assertion to:

```python
        assert wl.CONFIG_KEYS - app_keys == {"max_tokens", "chapter_numbering"}
```

Add two new tests to the class:

```python
    def test_chapter_numbering_is_position_on_both_backends(self):
        for backend in ("mlx", "ollama"):
            cfg = wl.build_config(_state(), backend)
            assert cfg["chapter_numbering"] == "position"

    def test_selected_chapters_follow_row_order(self):
        # Row order IS the processing order — a reordered list must come
        # out in display order, unchecked rows dropped, never re-sorted.
        rows = [wl.ChapterRow(4, "Epilogue", True),
                wl.ChapterRow(0, "Intro", True),
                wl.ChapterRow(2, "Two", False),
                wl.ChapterRow(1, "One", True)]
        cfg = wl.build_config(_state(chapters=rows), "mlx")
        assert cfg["selected_chapters"] == [4, 0, 1]
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_wizard_logic.py -v 2>&1 | tail -15`
Expected: `test_emits_exactly_the_23_contract_keys`, `test_covers_every_key_app_py_emits`, and `test_chapter_numbering_is_position_on_both_backends` FAIL (`chapter_numbering` missing / count 22). `test_selected_chapters_follow_row_order` already PASSES (the list comprehension preserves order) — that's fine; it pins the contract.

- [ ] **Step 3: Implement**

In `wizard_logic.py`:

(a) CONFIG_KEYS — update the comment and add the key:

```python
# Exactly what ProcessingWorker._run() reads. app.py emits the first 21;
# max_tokens and chapter_numbering are the wizard's additions.
CONFIG_KEYS: frozenset[str] = frozenset({
    "epub_path", "model", "backend", "selected_chapters", "mode", "level",
    "keep_pct", "creativity", "carry_mode", "summary_lang", "target_lang",
    "out_format", "out_folder", "generate_mp3", "voice",
    "meta_title", "meta_creator", "meta_language", "meta_contributor",
    "chunk_size", "timeout", "max_tokens", "chapter_numbering",
})
```

(b) `ChapterRow` docstring — replace the second paragraph line
`which is what worker.select_chapters() filters on. It is NOT the row's`
`position in this list.` with:

```python
    `index` is epub_io.Chapter.index — the stable 0-based document position,
    which is what epub_io.select_chapters() filters on. It is NOT the row's
    position in this list: the LIST ORDER is the user's processing order,
    and selected_chapters is emitted in that order.
```

(c) `build_config` — change the docstring's first line of para 2 from
`Emits all 22 keys on both backends.` to `Emits all 23 keys on both backends.`
and add to the returned dict, after `"max_tokens": state.max_tokens,`:

```python
        "chapter_numbering": "position",
```

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics wizard_logic.py tests/test_wizard_logic.py`
Expected: only the pre-existing `test_settings` failure; lint clean.

- [ ] **Step 5: Commit**

```bash
git add wizard_logic.py tests/test_wizard_logic.py
git commit -m "feat(wizard): chapter_numbering config key; selected_chapters order pinned

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Worker — position-based per-chapter file numbering

**Files:**
- Modify: `worker.py` (`_run`: cfg read ~line 115, per-chapter write ~403-408, book-key-ideas write ~432-438)
- Test: `tests/test_worker.py` (new class after `TestRunChapterSelection`, ~line 404)

**Interfaces:**
- Consumes: `cfg.get("chapter_numbering", "book")`; ordered `select_chapters` (Task 3).
- Produces: per-chapter txt files numbered `idx + 1` (processing position) when `chapter_numbering == "position"`, else `chapter.index + 1` (today's behaviour). Book-wide key-ideas file numbered `len(chapters) + 1` under position, `len(all_chapters) + 1` under book. `_write_chapter_file` signature unchanged.

- [ ] **Step 1: Write the failing tests**

Add after `TestRunChapterSelection` in `tests/test_worker.py` (same technique: patch `_llm_call` and `epub_io.extract_chapters`, real tmp filesystem; `_make_worker` and `patch` are already imported/defined in this module):

```python
class TestRunChapterOrdering:
    """selected_chapters is an ORDERED list: [2, 0] processes Gamma before
    Alpha. chapter_numbering='position' (wizard) numbers per-chapter files
    by processing position; absent/'book' (app.py) keeps full-list index."""

    CHAPTERS = [
        epub_io.Chapter(0, "c0.xhtml", "Alpha", "alpha text"),
        epub_io.Chapter(1, "c1.xhtml", "Beta", "beta text"),
        epub_io.Chapter(2, "c2.xhtml", "Gamma", "gamma text"),
    ]

    def _run(self, tmp_path, extra):
        cfg = {
            "epub_path": str(tmp_path / "mybook.epub"),
            "out_format": ["txt"],
            "out_folder": str(tmp_path),
            "mode": "translate",
            "level": "B2",
            "keep_pct": 40,
            "model": "m",
            "creativity": 5,
            "chunk_size": 2000,
            **extra,
        }
        w = _make_worker(cfg)
        with patch.object(ProcessingWorker, "_llm_call", return_value="texto"), \
                patch.object(epub_io, "extract_chapters",
                             return_value=self.CHAPTERS):
            w.run()
        return w

    def test_position_numbering_follows_custom_order(self, tmp_path):
        self._run(tmp_path, {"selected_chapters": [2, 0],
                             "chapter_numbering": "position"})
        files = sorted(
            p.name for p in (tmp_path / "mybook_ES_B2_chapters").glob("*.txt")
        )
        assert files == ["01 - Gamma.txt", "02 - Alpha.txt"]

    def test_default_book_numbering_keeps_fulllist_index(self, tmp_path):
        self._run(tmp_path, {"selected_chapters": [2, 0]})
        files = sorted(
            p.name for p in (tmp_path / "mybook_ES_B2_chapters").glob("*.txt")
        )
        assert files == ["01 - Alpha.txt", "03 - Gamma.txt"]

    def test_position_numbering_places_book_key_ideas_after_last(self, tmp_path):
        # summarise_key_ideas with >= 2 chapters appends a book-wide file;
        # under position numbering its NN follows the PROCESSED count
        # (2 chapters -> '03 - ...'), not the full-list count (which would
        # give '04 - ...' with 3 extracted chapters).
        self._run(tmp_path, {"selected_chapters": [2, 0],
                             "chapter_numbering": "position",
                             "mode": "summarise_key_ideas",
                             "summary_lang": "en"})
        files = sorted(
            p.name for p in (tmp_path / "mybook_ES_B2_chapters").glob("*.txt")
        )
        assert len(files) == 3
        assert files[0].startswith("01 - Gamma")
        assert files[1].startswith("02 - Alpha")
        assert files[2].startswith("03 - ")
        assert not any(f.startswith("04 - ") for f in files)
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_worker.py::TestRunChapterOrdering -v`
Expected: `test_position_numbering_follows_custom_order` FAILS — `chapter_numbering` is not read yet, so files come out book-numbered as `["01 - Alpha.txt", "03 - Gamma.txt"]`, not the asserted `["01 - Gamma.txt", "02 - Alpha.txt"]`. `test_position_numbering_places_book_key_ideas_after_last` FAILS (a `04 - ` book file exists and chapter files are book-numbered). `test_default_book_numbering_keeps_fulllist_index` PASSES (it pins existing behaviour).

- [ ] **Step 3: Implement**

In `worker.py` `_run`, next to the other cfg reads (after `resume_from = cfg.get("resume_from", 0)`):

```python
        numbering = cfg.get("chapter_numbering", "book")
```

Per-chapter write (currently passes `chapter.index`):

```python
            if "txt" in out_formats:
                self._write_chapter_file(
                    out_folder, stem, level,
                    idx if numbering == "position" else chapter.index,
                    chapter.title,
                    chapter_body,
                )
```

Book key-ideas write (currently passes `len(all_chapters)`; keep the existing comment, adjust it):

```python
                if "txt" in out_formats:
                    # NN lands right after the last chapter file: processed
                    # count under position numbering, full-list count under
                    # book numbering; title is the localized book header.
                    self._write_chapter_file(
                        out_folder, stem, level,
                        len(chapters) if numbering == "position"
                        else len(all_chapters),
                        book_header, book_body,
                    )
```

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics worker.py tests/test_worker.py`
Expected: only the pre-existing `test_settings` failure. Lint: `tests/test_worker.py` clean; `worker.py` shows exactly its pre-existing baseline (1×E501, 4×W503 — see Global Constraints), nothing new.

- [ ] **Step 5: Verify class boundaries (str_replace history — CLAUDE.md known issue)**

Run: `grep -n "^class " worker.py`
Expected: `37:class ProcessingWorker(QThread):` only.

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat(worker): chapter_numbering=position numbers chapter files by processing order

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Wizard UI — reorderable `TriStateChapterList`

Rework `TriStateChapterList` (`wizard_widgets.py:507-590`) from a QVBoxLayout of QCheckBoxes onto a QListWidget with drag-and-drop (`InternalMove`) plus per-row ▲▼ buttons, and live `NN.` renumbering. Public API is preserved (`set_chapters`, `rows`, `clear`, `selectionChanged`) so `StepBook` (`wizard_steps.py`) needs **no changes**. pytest stubs PyQt6, so behaviour is verified with an offscreen script.

**Known Qt pitfalls this design already accounts for (do not "simplify" them away):**
- After an `InternalMove` drag, Qt serializes/recreates the moved item and **drops its `setItemWidget` widget** — `_relabel()` re-creates every row's button widget after each move.
- `setItemWidget` spans the full item rect; the container must stay background-transparent with a leading stretch so the item's own checkbox/text show through and clicks/drags on the non-button area propagate to the viewport.
- Items must NOT have `ItemIsDropEnabled`, otherwise a drag can drop *onto* a row and nest/swallow it.
- `setText`/`setCheckState` fire `itemChanged` — wrap programmatic mutations in `blockSignals(True/False)` on the QListWidget.

**Files:**
- Modify: `wizard_widgets.py` (imports ~lines 13-29; replace class at 507-590; add `_RowMoveButtons` before it)
- Modify: `wizard_theme.py` (~line 214-225: extend checkbox indicator rules to QListView)
- Create: `scripts/verify_chapter_list.py` (offscreen verification, committed for reuse)

**Interfaces:**
- Consumes: `wl.ChapterRow` (frozen dataclass; `dataclasses.replace` already imported in wizard_widgets), `W_INSET`, `W_BORDER`, `W_ROW_HOVER`, `W_MUTED`, `W_TEXT_SECONDARY` from wizard_theme.
- Produces: same public API as before — `set_chapters(rows: list[ChapterRow])`, `rows() -> list[ChapterRow]` (**now in display order**, checked-state applied), `clear()`, `selectionChanged` signal (emitted on check toggles AND reorders — `StepBook._on_selection_changed` refreshes the meta and revalidates). New module-level class `_RowMoveButtons(QWidget)` with signals `moveUp`/`moveDown` and method `set_edges(first: bool, last: bool)`.

- [ ] **Step 1: Write the offscreen verification script (the "failing test")**

Create `scripts/verify_chapter_list.py`:

```python
"""Offscreen behaviour check for the reorderable TriStateChapterList.
pytest stubs PyQt6, so this runs as a plain script:
    QT_QPA_PLATFORM=offscreen python scripts/verify_chapter_list.py
Prints PASS/FAIL per check; exits non-zero on any FAIL."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QModelIndex, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wizard_logic as wl  # noqa: E402
from wizard_widgets import TriStateChapterList  # noqa: E402

app = QApplication([])
failures = []


def check(name: str, cond: bool) -> None:
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        failures.append(name)


lst = TriStateChapterList()
emitted = []
lst.selectionChanged.connect(lambda: emitted.append(1))
rows = [wl.ChapterRow(0, "Intro", True), wl.ChapterRow(1, "One", True),
        wl.ChapterRow(2, "Two", False), wl.ChapterRow(3, "Epilogue", True)]
lst.set_chapters(rows)

check("initial order", [r.index for r in lst.rows()] == [0, 1, 2, 3])
check("initial checked", [r.checked for r in lst.rows()]
      == [True, True, False, True])
check("initial labels renumbered",
      lst._list.item(0).text() == "01.  Intro"
      and lst._list.item(3).text() == "04.  Epilogue")

# ▲▼ buttons: move Epilogue (row 3) up one.
emitted.clear()
lst._move_item(lst._list.item(3), -1)
check("button move: order", [r.index for r in lst.rows()] == [0, 1, 3, 2])
check("button move: relabel", lst._list.item(2).text() == "03.  Epilogue")
check("button move: emits selectionChanged", len(emitted) == 1)

# Drag-and-drop path: model().moveRow triggers the same rowsMoved handler
# Qt fires after an InternalMove drop. Move row 2 (Epilogue) to the top.
emitted.clear()
lst._list.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)
check("drag move: order", [r.index for r in lst.rows()] == [3, 0, 1, 2])
check("drag move: relabel", lst._list.item(0).text() == "01.  Epilogue")
check("drag move: emits selectionChanged", len(emitted) >= 1)
check("drag move: item widgets restored",
      all(lst._list.itemWidget(lst._list.item(i)) is not None
          for i in range(lst._list.count())))

# Checked state survives reorders; toggling still works.
check("checked survives moves",
      [r.checked for r in lst.rows()] == [True, True, True, False])
emitted.clear()
lst._list.item(0).setCheckState(Qt.CheckState.Unchecked)
check("toggle: rows() reflects", lst.rows()[0].checked is False)
check("toggle: emits selectionChanged", len(emitted) == 1)

# Edge buttons disabled at the ends.
top = lst._list.itemWidget(lst._list.item(0))
bottom = lst._list.itemWidget(lst._list.item(3))
check("top row ▲ disabled", not top._up.isEnabled() and top._down.isEnabled())
check("bottom row ▼ disabled",
      bottom._down.isEnabled() is False and bottom._up.isEnabled())

# rows() round-trips through set_chapters (StepBook load_from path).
lst.set_chapters(lst.rows())
check("round-trip keeps order", [r.index for r in lst.rows()] == [3, 0, 1, 2])

lst.grab().save("/tmp/chapter_list.png")
print("screenshot -> /tmp/chapter_list.png")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run to verify it fails against the current widget**

Run: `QT_QPA_PLATFORM=offscreen python scripts/verify_chapter_list.py; echo "exit=$?"`
Expected: crashes (no `_list`/`_move_item` attributes on the current implementation) or FAIL lines; exit non-zero.

- [ ] **Step 3: Extend the theme stylesheet for QListWidget items**

In `wizard_theme.py`, the indicator block at ~line 214 currently styles `QCheckBox` only. Item checkboxes in a QListWidget use `QListView::indicator` selectors — extend each of the five rules to cover both, keeping identical values:

```python
QCheckBox, QRadioButton {{ spacing: 8px; color: {W_TEXT}; background: transparent; }}
QCheckBox::indicator, QListView::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1.5px solid {W_BORDER_CTRL}; background: {W_INSET};
}}
QCheckBox::indicator:checked, QListView::indicator:checked {{
    background-color: {W_AMBER}; border-color: {W_AMBER};
}}
QCheckBox::indicator:indeterminate, QListView::indicator:indeterminate {{
    background-color: {W_BTN_DISABLED_BG}; border-color: {W_AMBER_DIM};
}}
QCheckBox::indicator:disabled, QListView::indicator:disabled {{
    border-color: {W_BORDER}; background: {W_WINDOW_BG};
}}
```

(The disabled rule is split across lines — the combined selector would exceed the 100-char lint limit on one line.)

- [ ] **Step 4: Implement the widget**

In `wizard_widgets.py`:

(a) Imports — add `partial` and the new Qt classes:

```python
from dataclasses import replace
from functools import partial
```

and extend the QtWidgets import to include `QAbstractItemView, QListWidget, QListWidgetItem, QToolButton` (keep the existing names, alphabetical order, line length ≤ 100):

```python
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QRadioButton,
    QScrollArea, QSizePolicy, QSlider, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)
```

Extend the wizard_theme import with `W_TEXT_SECONDARY` if not already imported (it is — see line 27). `QScrollArea` remains used by other widgets; do not remove it.

(b) Replace the entire `TriStateChapterList` class (lines 507-590) with `_RowMoveButtons` + the new implementation:

```python
class _RowMoveButtons(QWidget):
    """▲▼ pair docked at the right edge of a chapter row.

    Lives in a full-row setItemWidget overlay: a leading stretch keeps the
    buttons right-aligned, and the container paints no background, so the
    item's own checkbox/text stay visible and presses outside the buttons
    fall through to the viewport (which is what lets drag still work)."""

    moveUp = pyqtSignal()
    moveDown = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(0)
        lay.addStretch()
        self._up = QToolButton()
        self._up.setText("▲")
        self._down = QToolButton()
        self._down.setText("▼")
        for btn, sig in ((self._up, self.moveUp), (self._down, self.moveDown)):
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QToolButton {{ color:{W_MUTED}; border:none;"
                f" background:transparent; padding:0 2px; }}"
                f"QToolButton:hover {{ color:{W_TEXT_SECONDARY}; }}"
            )
            btn.clicked.connect(sig)
            lay.addWidget(btn)

    def set_edges(self, first: bool, last: bool) -> None:
        self._up.setEnabled(not first)
        self._down.setEnabled(not last)


class TriStateChapterList(QWidget):
    """'Select all' tri-state master + a drag-reorderable chapter list.

    Row order IS the processing order: rows() returns ChapterRows in display
    order, and labels renumber live ('01.', '02.', …) after every drag or
    ▲▼ move. selectionChanged fires on check toggles AND on reorders."""

    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._master = QCheckBox("Select all")
        self._master.setTristate(True)
        self._master.clicked.connect(self._on_master_clicked)
        layout.addWidget(self._master)

        self._list = QListWidget()
        self._list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list.setMaximumHeight(188)
        self._list.setStyleSheet(
            f"QListWidget {{ background:{W_INSET};"
            f" border:1px solid {W_BORDER}; border-radius:8px;"
            f" padding:4px; }}"
            f"QListWidget::item {{ padding:2px 4px; border-radius:4px; }}"
            f"QListWidget::item:hover {{ background:{W_ROW_HOVER}; }}"
            f"QListWidget::item:selected {{ background:{W_ROW_HOVER}; }}"
        )
        self._list.itemChanged.connect(self._on_item_changed)
        # Fires after an InternalMove drop; also reachable programmatically
        # via model().moveRow (the offscreen script uses that).
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self._list)

    # ── public API (unchanged from the pre-reorder widget) ──
    def clear(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._sync_master()

    def set_chapters(self, rows: list["wl.ChapterRow"]) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for row in rows:
            item = QListWidgetItem()
            # No ItemIsDropEnabled: dropping ONTO a row would nest it.
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked if row.checked
                else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._relabel()
        self._sync_master()

    def rows(self) -> list["wl.ChapterRow"]:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            out.append(replace(
                row,
                checked=item.checkState() == Qt.CheckState.Checked,
            ))
        return out

    # ── internals ──
    def _relabel(self) -> None:
        """Renumber every label to its display position and (re)attach the
        ▲▼ row widgets — Qt drops setItemWidget widgets on InternalMove, so
        this runs after every reorder, not just on set_chapters."""
        count = self._list.count()
        self._list.blockSignals(True)
        for i in range(count):
            item = self._list.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            item.setText(f"{i + 1:02d}.  {row.title}")
            buttons = _RowMoveButtons()
            buttons.set_edges(i == 0, i == count - 1)
            buttons.moveUp.connect(partial(self._move_item, item, -1))
            buttons.moveDown.connect(partial(self._move_item, item, +1))
            self._list.setItemWidget(item, buttons)
        self._list.blockSignals(False)

    def _move_item(self, item: QListWidgetItem, delta: int) -> None:
        pos = self._list.row(item)
        new_pos = pos + delta
        if not 0 <= new_pos < self._list.count():
            return
        self._list.blockSignals(True)
        taken = self._list.takeItem(pos)
        self._list.insertItem(new_pos, taken)
        self._list.setCurrentRow(new_pos)
        self._list.blockSignals(False)
        self._relabel()
        self.selectionChanged.emit()

    def _on_rows_moved(self, *_args) -> None:
        self._relabel()
        self.selectionChanged.emit()

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._sync_master()
        self.selectionChanged.emit()

    def _on_master_clicked(self) -> None:
        # A tri-state master must drive children to a definite state, never
        # leave them Partially — clicking it always means "all" or "none".
        target = (
            Qt.CheckState.Checked
            if self._master.checkState() != Qt.CheckState.Unchecked
            else Qt.CheckState.Unchecked
        )
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(target)
        self._list.blockSignals(False)
        self._sync_master()
        self.selectionChanged.emit()

    def _sync_master(self) -> None:
        total = self._list.count()
        checked = sum(
            1 for i in range(total)
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        )
        self._master.blockSignals(True)
        if total and checked == total:
            self._master.setCheckState(Qt.CheckState.Checked)
        elif checked == 0:
            self._master.setCheckState(Qt.CheckState.Unchecked)
        else:
            self._master.setCheckState(Qt.CheckState.PartiallyChecked)
        self._master.blockSignals(False)
```

- [ ] **Step 5: Run the offscreen script to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python scripts/verify_chapter_list.py; echo "exit=$?"`
Expected: every line `PASS`, `exit=0`. Open `/tmp/chapter_list.png` (Read tool) and confirm: rows show `01.`-prefixed labels, styled checkboxes, right-aligned ▲▼ per row, top row's ▲ greyed.

- [ ] **Step 6: Full suite + lint + class boundaries**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics wizard_widgets.py wizard_theme.py scripts/verify_chapter_list.py && grep -n "^class " wizard_widgets.py`
Expected: only the pre-existing `test_settings` failure; lint clean; class list = `Card, Note, _ProgressPill, RunConsole, _SliderTrack, WizardSlider, _ClickableLabel, _ClickableTile, StepRail, ModeTileGrid, _RowMoveButtons, TriStateChapterList` (all `(Q...)` bases intact).

- [ ] **Step 7: Launch the wizard for a real drag check**

Run: `python wizard.py` (needs the user's display; if running unattended, skip and note it in the handoff — the drag path is the one thing offscreen can't fully prove).
Expected: import `books/mattering_too/Mattering_-_Jennifer_Breheny_Wallace.epub`, drag a row by its text area, watch labels renumber; ▲▼ move single steps; "n / m selected" meta stays correct.

- [ ] **Step 8: Commit**

```bash
git add wizard_widgets.py wizard_theme.py scripts/verify_chapter_list.py
git commit -m "feat(wizard): drag + ▲▼ chapter reordering with live renumbering

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Documentation — CLAUDE.md and README.md

**Files:**
- Modify: `CLAUDE.md` (pipeline config table; `selected_chapters` row; wizard_logic file-map row; class grep list)
- Modify: `README.md` (Chapter selection feature row)

**Interfaces:** none — docs only.

- [ ] **Step 1: CLAUDE.md — config table**

In the "Config keys relevant to the pipeline" table, replace the `selected_chapters` row with:

```markdown
| `selected_chapters` | `list[int]` | Indices (into the extracted chapter list) the user ticked, **in processing order** — the wizard lets the user reorder rows and the worker processes in list order (`epub_io.select_chapters` honours it). `app.py` sends sorted indices (book order). `None`/absent means all |
```

and add a new row after `backend`:

```markdown
| `chapter_numbering` | `str` | `"book"` (default; per-chapter txt files numbered `chapter.index + 1`) or `"position"` (numbered by processing position — the wizard sets this so file numbers match its reordered list) |
```

- [ ] **Step 2: CLAUDE.md — file map + per-chapter file description**

- In the file map row for `wizard_logic.py`, change "the 22-key `build_config` worker contract" to "the 23-key `build_config` worker contract".
- In the "Per chapter" pipeline section, step 4 ("Per-chapter file (txt only)"), change "where `NN` is `index + 1` (the number shown in the UI chapter list)" to "where `NN` is `index + 1` for `chapter_numbering: "book"` or the processing position + 1 for `"position"` — either way the number shown in that frontend's chapter list".
- In "What this project does" nothing changes (mode descriptions are order-agnostic).

- [ ] **Step 3: CLAUDE.md — class grep list**

Run: `grep -n "^class " *.py`
Replace the expected-output block in the "Known historical issues" section with the actual current output (it gains `wizard_widgets.py:…:class _RowMoveButtons(QWidget):` and all shifted line numbers).

- [ ] **Step 4: README.md — feature row**

Replace the Chapter selection row:

```markdown
| Chapter selection | Scrollable checklist of every chapter with a tri-state "Select all"; process any subset (≥1 required). The wizard frontend additionally supports reordering chapters (drag-and-drop or ▲▼) — processing, all output formats, and the MP3 follow the custom order |
```

- [ ] **Step 5: Verify docs claims against reality**

Run: `python -m pytest tests/ -q && grep -c "chapter_numbering" CLAUDE.md`
Expected: only the pre-existing `test_settings` failure; grep count ≥ 2.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: ordered selected_chapters, chapter_numbering key, wizard reordering

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
