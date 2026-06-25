# Chapter selection + incremental per-chapter txt output — design

**Date:** 2026-06-25
**Status:** Approved (pending spec review)

## Goal

Let the user pick exactly which chapters of a selected EPUB get processed, and
— when plain-text output is enabled — write each chapter's result to disk as it
finishes (in addition to the existing assembled output).

User requirements (verbatim intent):

- On book selection, show a list of chapters. Show chapter titles if present;
  otherwise the first N characters of the body (N configurable).
- A checkbox before each chapter, plus a "Select all" checkbox.
- Whatever the processing mode (summarise → rewrite, full translation,
  summarise-only), only the **selected** chapters are processed.
- When `txt` is a selected output format: keep the current way of assembling the
  results **and** write each chapter's result to the output folder as it is
  processed.

Cross-cutting constraints from the user: **state of the art**, **no code
duplication**, **ask — never assume**.

## Decisions (confirmed with the user)

1. **Title source:** EPUB TOC/nav first, then fallbacks (first heading, then text
   preview).
2. **`first_only` checkbox:** removed — the per-chapter selection list (with
   Select All) fully supersedes it.
3. **Per-chapter file location/naming:** a subfolder, files named
   `NN - Title.txt`.
4. **Modes:** per-chapter files are written for **all** modes, but **only when
   `txt`** is one of the selected output formats.

Author's calls (flagged, open to change in review):

- Per-chapter **filenames use the real chapter title**; the **assembled txt keeps
  the current synthesized `Capítulo N` / `Chapter N` titles** (honoring "keep
  current way of assembling the results").
- Per-chapter file number = the chapter's position in the displayed list
  (`index + 1`), so selecting chapters 3/7/12 yields `03 …`, `07 …`, `12 …`.

## Architecture

### New shared module: `epub_io.py`

The single source of truth for turning an EPUB into chapters. Both `app.py`
(to build the selection list) and `worker.py` (to process) call it.

> **Invariant:** chapter extraction is implemented **only** here. Positional
> chapter indices are stable between the app-side read and the worker-side read
> *only because* both go through this one function. Do not reimplement
> extraction anywhere else.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Chapter:
    index: int      # 0-based position in the extracted list — the stable ID
    doc_name: str   # item.get_name()
    title: str      # resolved display title
    text: str       # body text

def extract_chapters(path: str, preview_chars: int = 50) -> list[Chapter]:
    ...
```

**Title resolution** (per chapter document):

1. Flatten `book.toc` (handles both `Link` entries and `(Section, [children])`
   tuples) into a map of `basename(href without #anchor)` → title. Use the first
   TOC entry whose href basename matches the document name.
2. Else: first `<h1>` / `<h2>` / `<h3>` / `<title>` text found in the document.
3. Else: the first `preview_chars` characters of the body text (stripped).

**Document filter:** unchanged from today — an `ITEM_DOCUMENT` whose extracted
text length is `> 200` chars becomes a chapter. The checkbox list now also lets
the user deselect any front/back matter that slips past this heuristic.

**Import rules:** `epub_io` → `ebooklib` / `bs4` only. Never Qt, never `app`,
`worker`, or `settings`. `preview_chars` is passed in by callers (read from
`SETTINGS`), keeping the module pure and unit-testable. `epub_io` is imported
**lazily** (inside the functions that use it) so EPUB/torch-adjacent import cost
is not paid at app startup — matching the existing lazy-import pattern.

### UI: reusable `ChapterListWidget` in `widgets.py`

Generic and decoupled from `epub_io` — it operates on `(index, label)` pairs
only, preserving the existing `widgets → settings` import boundary.

- A **"Select all"** checkbox (tri-state; reflects the children's combined
  state, and toggles them all when clicked).
- A **scroll area** containing one `QCheckBox` per chapter, labeled
  `01. <title>`, `02. <title>`, …
- API: `set_chapters(pairs: list[tuple[int, str]])`, `selected_indices() ->
  list[int]`, and a method/clear to reset when a new book is loaded.

`app.py` wiring:

- `_on_epub_selected()` calls `epub_io.extract_chapters(path, preview_chars)`,
  stores the `Chapter` list on the app instance, and feeds
  `(index, f"{index+1:02d}. {title}")` pairs into the widget.
- **Default on load:** all chapters checked, Select-All checked. (No carry-over
  from the removed `first_only`.)
- A new "Chapters" group hosts the widget, placed after the Source group.

Extraction runs on the UI thread at selection time. Acceptable for a novel-sized
book; no async machinery is built now.

## Config & worker changes

### `_build_config` (app.py)

- Add `"selected_chapters": sorted(self._chapter_list.selected_indices())`.
- Validate **≥ 1 chapter selected** (same warning style as the existing
  "select at least one output format" / "select an EPUB" checks). Returns `None`
  to abort the run if nothing is selected.
- Remove `"first_only"`.

### `worker.run` (worker.py)

- Replace the inline extraction block with
  `chapters = epub_io.extract_chapters(epub_path, preview_chars)`.
- Filter: `selected = set(cfg.get("selected_chapters", ...)); chapters = [c for c
  in chapters if c.index in selected]`.
- Remove the `first_only` (`chapters[:1]`) branch.
- `total_steps`, the progress loop, log labels, and resume logic all operate on
  the **filtered** list.
- Chapter objects (`c.index`, `c.title`) are used for per-chapter file naming.
  The assembled `results` list keeps the synthesized titles as today.

### Pipeline config key

`preview_chars` is read by app and worker from
`SETTINGS.get("chapter_title_preview_chars", 50)`.

## Per-chapter txt output (all modes, only when `txt` selected)

Inside the chapter loop, after a chapter's result is assembled (`"\n\n".join(
spanish_parts)`), if `"txt"` is in `out_format`:

- **Subfolder:** `{assembled_stem}_chapters/` under the output folder
  (`{assembled_stem}` is the same stem the assembled `.txt` file uses).
- **Filename:** `f"{c.index + 1:02d} - {sanitised_title}.txt"`. Title sanitised
  for the filesystem (strip/replace path separators and illegal characters,
  collapse whitespace, trim length).
- **No duplication:** a single `_chapter_block(title, body) -> str` helper
  produces the `=`-delimited block. Both the per-chapter writer and the existing
  `_write_txt` assembly call it. The per-chapter file uses the **real** chapter
  title; the assembled file uses the synthesized `Capítulo N` / `Chapter N`
  title as today.

The assembled output (`_write_txt`) is otherwise unchanged.

## Resume threading (highest-risk integration point)

- `resume_from` remains an index into the **filtered** chapter list.
- `completed_results` / `failed_at_chapter` index the filtered list.
- `_on_resume` re-injects the same `selected_chapters` into the resume config so
  the resumed run processes exactly the same subset (mirrors the existing
  "Adding a UI control → step 3" pattern in CLAUDE.md).
- Per-chapter files already written by the prior run are left in place; the loop
  skips already-completed indices, so they are not rewritten.

## Edge cases

- **No chapters selected:** `_build_config` warns and aborts (returns `None`).
- **New book selected after a previous one:** the chapter list is rebuilt and
  re-defaulted to all-checked.
- **Duplicate / colliding sanitised titles:** the `NN -` numeric prefix (unique
  per chapter index) guarantees filename uniqueness.
- **TOC mapping miss:** falls through to heading, then text preview — no hard
  failure.

## Documentation updates (`CLAUDE.md`)

- **Architecture rule 1 (import graph):** add `app → epub_io` and
  `worker → epub_io` (lazy); document `epub_io → ebooklib/bs4 only`.
- **File map:** add the `epub_io.py` row; note `worker.py` no longer extracts
  chapters inline.
- **Pipeline config-keys table:** drop `first_only`; add `selected_chapters`.
- **Configuration system:** add `chapter_title_preview_chars`.
- **Resume system:** note `selected_chapters` is re-injected on resume.
- **Pipeline output section:** document the per-chapter txt files.

## Out of scope (YAGNI)

- Asynchronous/background chapter extraction.
- Per-chapter output for EPUB/HTML formats (txt only, per requirement).
- Changing the assembled output's title scheme.
- Reordering / renaming chapters in the UI.