# Chapter names + user-defined processing order (wizard) — design

**Date:** 2026-07-14
**Status:** approved

## Problem

1. Chapter titles come only from the NCX TOC (via ebooklib's `book.toc`);
   EPUB3 books that ship only a `nav.xhtml` TOC fall back to headings or
   text previews. The list should show real chapter names whenever any
   source in the book provides one (a bare number like "3" counts).
2. Chapters are always processed in book (spine) order. The user wants to
   reorder chapters in the wizard's chapter list, and have that order
   honoured in processing and in every output: txt, epub, html — and MP3.

Scope decisions (confirmed with the user):

- Reordering UI: **wizard frontend only**. The original `app.py` stays
  selection-only and behaves byte-identically.
- Reorder interaction: **both** drag-and-drop and per-row ▲▼ buttons.
- Numbering: **renumber to the new order** — the on-screen list and the
  per-chapter txt filenames use the chapter's position in the custom
  order (first row is always 01).
- Persistence: **per-run only.** No saved order; re-importing a book
  starts fresh in book order. Order rides resume via the existing
  `**config` spread.

## 1. Better chapter names — regression pin + dependency floor

**Amended 2026-07-14 (approved by user):** investigation showed that
ebooklib 0.20 (the installed version) already parses the EPUB3
`nav.xhtml` TOC into `book.toc` — nav-only books get real chapter names
through the existing `_flatten_toc` path, and when both NCX and nav are
present, the nav title wins. Writing our own nav parser would be dead
code, so no BookWeaver parsing change is made. Instead:

- Add a regression test pinning that a nav-only EPUB (empty NCX)
  resolves real chapter names via the existing chain.
- Raise the dependency floor from `ebooklib>=0.18` to `ebooklib>=0.20`
  (in `pyproject.toml` and `requirements.txt`) so the guarantee holds on
  fresh installs.

The resolution chain stays as implemented:
**TOC (`book.toc`: NCX and/or nav, per ebooklib) → h1/h2/h3 → `<title>`
tag → text preview → filename.** A TOC entry that is just a number is
used as-is.

## 2. Ordered selection — `epub_io.select_chapters` + `wizard_logic`

`select_chapters(chapters, indices)` changes semantics: it returns the
chapters **in the order the indices are listed** (previously: filtered
set, document order). Unknown indices are still ignored; `indices is
None` still means "all chapters, book order".

- `wizard_logic.build_config` already emits
  `[r.index for r in state.chapters if r.checked]`; once `state.chapters`
  reflects display order, `selected_chapters` is automatically an ordered
  list. No config key is added or renamed for ordering.
- `app.py` sends sorted indices → original app behaviour unchanged.
- Resume: order rides the `**config` spread like selection does today.
  `resume_from` indexes into the ordered-filtered list, which is stable
  across resume. No resume changes.
- `ChapterRow.index` stays the stable EPUB identity (position in the
  extracted list). Display position is the row's place in the list —
  a distinct concept.

## 3. Wizard UI — rework `TriStateChapterList` (`wizard_widgets.py`)

Replace the QVBoxLayout-of-QCheckBoxes with a **QListWidget**:

- Items checkable (`ItemIsUserCheckable`) and drag-reorderable
  (`InternalMove`).
- Each row also carries **▲▼ buttons** (row widget via `setItemWidget`)
  for single-step moves; disabled at the list edges.
- Labels show `NN. Title` where NN = row position + 1, **renumbered
  live** after every drag (`model().rowsMoved`) and every button move.
- Public API preserved: `set_chapters(rows)`, `rows()` (returns display
  order), `selectionChanged` (now also emitted on reorder, keeping the
  "n / m selected" card meta and step validation live). `StepBook`
  needs no logic change.
- Styling reuses the existing `wizard_theme` palette values
  (`W_INSET`/`W_BORDER`/`W_ROW_HOVER`); no hardcoded hex (CLAUDE.md
  rule 2).

## 4. Worker — position-based per-chapter numbering (`worker.py`)

New optional config key **`chapter_numbering`**:

| Value | Meaning |
|---|---|
| `"book"` (default) | today's behaviour: NN = `chapter.index + 1` |
| `"position"` | NN = position in the processing sequence (`idx + 1`) |

The wizard's `build_config` sets `"position"` (contract grows to 23
keys; contract test updated). `app.py` doesn't set it and keeps book
numbering. Under `"position"`, the book-wide key-ideas file's NN
follows the last processed chapter (`len(chapters)`, the filtered list,
instead of `len(all_chapters)`).

Outputs need no changes: the txt/epub/html writers and
`tts.synthesise_book()` all iterate `results`, which is built in
processing order — MP3 order follows automatically (verified at
`worker.py:525`, `chapters=results`).

## 5. Testing

- `test_epub_io.py`: nav-TOC title extraction (fixture EPUB with a
  nav-only TOC); NCX-wins-over-nav merge; `select_chapters` honours the
  given order (replaces `test_filters_and_preserves_order`).
- `test_wizard_logic.py`: `build_config` emits `selected_chapters` in
  row order; contract count 23; `chapter_numbering: "position"`.
- `test_worker.py`: `_write_chapter_file` numbering under both
  `chapter_numbering` modes, including the book key-ideas file.
- Qt widget behaviour (drag, buttons, live renumbering): verified via an
  offscreen script, per project convention — pytest stubs PyQt6.

## 6. Documentation

- **CLAUDE.md**: `selected_chapters` documented as an *ordered* list;
  new `chapter_numbering` key in the pipeline config table;
  `TriStateChapterList` description updated; class-boundary grep list
  refreshed if class lines move.
- **README.md**: chapter-selection feature row updated to mention
  reordering in the wizard; title-resolution description updated
  (NCX + nav TOC sources).

## Out of scope

- Reordering in the original `app.py` frontend.
- Persisting a custom order across sessions.
- Any change to chunking, continuity carry, or scene-break handling
  (all within-chapter; unaffected by chapter order).
