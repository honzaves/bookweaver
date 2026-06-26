# Summary with Key Ideas — Design

**Date:** 2026-06-26
**Status:** Approved (brainstorming) — ready for implementation plan

---

## 1. Summary

Add a fourth processing mode to BookWeaver:
**"Summary with key ideas"** (`mode = "summarise_key_ideas"`).

It reuses BookWeaver's existing summary pipelines, then appends:

- **Per-chapter key ideas** — at the end of each chapter, 1–5 key ideas/moments,
  each rendered as a bullet plus a short explanation (≤ 2 sentences).
- **Book-wide synthesis** — after all chapters are processed, *if 2 or more
  chapters were processed*, a final "Key ideas of the book" section presenting
  the most important ideas across the whole book (same bullet + ≤ 2-sentence
  format).

Output language is chosen **per run**: English, or Spanish at the selected
CEFR level.

The user flow is unchanged from existing modes: select EPUB → chapters appear →
select chapters → select this mode → set reduction (keep %), creativity, output
format(s) → run.

---

## 2. Goals / Non-goals

### Goals
- New mode that produces a condensed summary **plus** key ideas per chapter
  **plus** a whole-book synthesis.
- Per-run language choice (English / Spanish at CEFR level).
- Reuse existing prompt builders and pipeline machinery (DRY).
- Resume works exactly as it does for other modes.

### Non-goals
- No new output formats (txt/epub/html/MP3 all work unchanged).
- No change to existing modes' behaviour.
- No special MP3/TTS handling — key ideas are part of the chapter body and read
  aloud like any other text.
- No new EPUB extraction or chapter-selection logic — that flow is reused as-is.

---

## 3. Language choice (the central decision)

The mode supports **both** English and Spanish output, selected per run via a
small language toggle shown only when this mode is active.

| Choice | Summary production | CEFR level |
|---|---|---|
| English | `build_summary_prompt` per chunk (1 LLM call/chunk) | ignored |
| Spanish | `build_summary_prompt` → `build_rewrite_prompt` per chunk (2 LLM calls/chunk) | applied |

The Spanish path deliberately reuses the existing **Summarise → Rewrite**
pipeline (condense to English, then rewrite into literary Spanish at the CEFR
level) rather than condensing directly into Spanish. This keeps prose quality
consistent with the flagship mode and avoids a redundant prompt builder.

Key ideas and the book synthesis are always produced **in the chosen output
language**.

---

## 4. UI changes (`app.py`)

1. **New radio button** in the Processing mode group
   (`_add_summarisation_group`): **"Summary with key ideas"**.
   Add it to `self._mode_group` and the toggle wiring loop.

2. **Language toggle** — a small two-button selector (English / Spanish)
   inside the Processing mode group, visible **only** when this mode is
   selected. Default: Spanish (matches the app's primary purpose). The existing
   CEFR combo in the "Model & Target Language" group is reused when Spanish is
   chosen; it is ignored for English (exactly as `summarise_only` already
   ignores it).

3. **`_on_mode_changed()`** updates visibility:
   - Summarisation-depth slider: visible (reduction applies to this mode).
   - Language toggle: visible only for this mode.
   - Existing translate/summarise-only notes: unchanged.
   - Rebuild the voice combo (the toggle changes the target language, hence the
     voice list), reusing the existing `_rebuild_voice_combo()` path.

4. **`_selected_mode()`** returns `"summarise_key_ideas"` when the new radio is
   checked.

5. **`_build_config()`** adds:
   - `mode` (already returned by `_selected_mode()`).
   - `summary_lang`: `"en"` or `"es"` from the toggle (only meaningful for this
     mode).
   - `target_lang`: for this mode, equals `summary_lang`; for other modes,
     `TARGET_LANG[mode]` as today. Implemented via a small helper so the
     computation has a single source of truth.

6. **`_on_resume()`** spreads `**self._resume_state["config"]`, so
   `summary_lang` / `target_lang` ride along automatically — no extra wiring
   (same pattern that already carries `selected_chapters`).

---

## 5. Prompts (`prompts.py`)

Two new builders, both language-aware, reusing `_LEVEL_GUIDANCE` and
`_creativity_instruction` (single source of truth):

### `build_key_ideas_prompt(summary_text, lang, level, creativity)`
- Input: the fully assembled chapter summary (post-join, post-rewrite).
- Output: **1–5** key ideas/moments — at least one, never more than five.
- Each idea = a bullet line + an explanation of ≤ 2 sentences.
- Written in `lang` (`"en"` → English; `"es"` → Spanish at CEFR `level`,
  applying `_LEVEL_GUIDANCE`).
- Proper-noun rule preserved (names not translated/altered).
- Output begins with a **localized section header** (see §6) so the worker can
  both render it and later locate it for the book synthesis.

### `build_book_key_ideas_prompt(chapter_key_ideas_text, lang, level, creativity)`
- Input: the concatenation of every processed chapter's key-ideas section.
- Output: the **most important ideas across the whole book** (cap: **5–7**),
  same bullet + ≤ 2-sentence format, in `lang`.
- Begins with the localized book-level header (see §6).

No existing prompt builder is modified.

---

## 6. Localized headers (single source of truth)

Define header constants (e.g. in `prompts.py`, exported for the worker):

| Key | English | Spanish |
|---|---|---|
| chapter key ideas | `Key ideas` | `Ideas clave` |
| book key ideas | `Key ideas of the book` | `Ideas clave del libro` |

The same constant is used to (a) instruct the LLM, (b) render the section, and
(c) extract per-chapter ideas for the book synthesis. One definition, three
uses — no drift.

---

## 7. Pipeline (`worker.py`)

### Per chapter (inside the existing chunk loop)
1. Produce the chapter summary using the language-appropriate path (§3),
   reusing the existing `summarise_only` / `summarise_rewrite` branches'
   prompt calls. Join chunk outputs with `\n\n` as today.
2. **One** `build_key_ideas_prompt(...)` call over the joined summary →
   key-ideas text (already includes its localized header).
3. **Chapter body** stored in `results` =
   `joined_summary + "\n\n" + key_ideas_text`.
   Embedding the ideas *in the body* (not a separate worker-side list) is what
   makes resume correct: a resumed run only receives `(title, body)` tuples via
   `prior_results`, so anything needed for the book synthesis must live in the
   body.
4. Per-chapter `.txt` file and the running `results` are written exactly as
   today (the body now simply includes the key-ideas section).

### After the loop (book synthesis)
- **Gate:** only if the number of processed chapters in `results` ≥ 2.
- Extract each chapter's key-ideas section from its body by locating the
  localized chapter header (§6); fall back to the whole body if the header is
  not found (defensive). This reads from `results` bodies, so it is correct on
  both fresh and resumed runs.
- One `build_book_key_ideas_prompt(...)` call → book synthesis text.
- Append `(localized_book_header_title, book_synthesis_body)` to `results` as a
  final entry, so the existing `_write_txt` / `_write_epub` / `_write_html`
  writers render it with no writer changes.
- Like TTS, this post-loop call is **excluded from `total_steps`** and reported
  via log lines only. A failure here is logged but must not fail the run (text
  output is already written) — same resilience posture as MP3.

### `target_lang` / `lang_label`
- `target_lang` comes from config (`summary_lang` for this mode).
- `lang_label` reflects the chosen language: `"English summary"` for English,
  `"Spanish {level}"` for Spanish — reusing the existing `lang_label` logic,
  extended to recognise this mode.

### Progress bar
- `steps_per_chapter` for this mode:
  - **English:** 2 (summary + key ideas)
  - **Spanish:** 3 (summary + rewrite + key ideas)
- `total_steps = len(processed_chapters) * steps_per_chapter`, consistent with
  the existing convention (progress is emitted once per chapter; chunk count
  does not change the total).
- The book-synthesis call is excluded (post-loop, log-only).

---

## 8. Settings (`settings.py`)

- Add `summarise_key_ideas` to `TARGET_LANG` with a default of `"es"`. The app
  overrides the effective target language per run via `summary_lang`, but the
  dict entry keeps `TARGET_LANG[mode]` total for any code that indexes it.

No colour, model, or other JSON changes required.

---

## 9. Output / filenames

- Output filename keeps the existing `{stem}_ES_{level}` scheme for **both**
  languages, mirroring `summarise_only` (which already writes English output to
  a `_ES_` filename). This avoids scope creep and keeps the writers untouched.
  (Noted as a known minor inconsistency; a future cleanup could switch English
  output to an `_EN_` name.)

---

## 10. Resume

No new resume code. Because key ideas are embedded in each chapter body and the
book synthesis is derived from `results` bodies, a resumed run:

- Seeds `results` from `prior_results` (bodies already contain key-ideas
  sections).
- Reprocesses only the remaining chapters.
- Recomputes the book synthesis at the end from the full `results` set.

`summary_lang` / `target_lang` carry through via the existing `**config`
spread in `_on_resume()`.

---

## 11. Testing

`tests/` stubs Qt, so the new logic is unit-testable as pure functions / file
I/O:

- **Prompt builders:** pin `build_key_ideas_prompt` and
  `build_book_key_ideas_prompt` output for English and Spanish — assert the
  1–5 / 5–7 caps are stated, the ≤ 2-sentence rule is present, the localized
  header appears, and the CEFR guidance is included for Spanish. (The existing
  builders already have pinned tests; follow that pattern.)
- **Header extraction helper:** the worker function that pulls key-ideas
  sections out of bodies — test header-found and header-missing (fallback)
  cases, for both languages.
- **Book-synthesis gate:** assert the synthesis entry is appended when ≥ 2
  chapters are processed and omitted for a single chapter.
- **`TARGET_LANG`** contains the new mode.

The Qt pipeline, live Ollama, and real TTS remain not unit-tested (unchanged
policy).

---

## 12. CLAUDE.md follow-through

Implementation must follow the existing **"Adding a new processing mode"**
checklist in `CLAUDE.md` (radio button → `_on_mode_changed` → `_build_config`
→ prompt builder → worker branch → `steps_per_chapter`). After edits that touch
class boundaries, run `grep -n "^class " *.py` and confirm the expected class
list (per the "Known historical issues" section).

`CLAUDE.md` itself should be updated to document the new mode (the "What this
project does" list, the pipeline config-keys table for `summary_lang`, and the
per-chapter / after-all-chapters pipeline sections).

---

## 13. File-by-file change summary

| File | Change |
|---|---|
| `prompts.py` | Add `build_key_ideas_prompt`, `build_book_key_ideas_prompt`, localized header constants |
| `app.py` | New radio button, language toggle, `_on_mode_changed` / `_selected_mode` / `_build_config` updates |
| `worker.py` | New mode branch, per-chapter key-ideas call, post-loop book synthesis, `steps_per_chapter`, `lang_label`, header-extraction helper |
| `settings.py` | `TARGET_LANG["summarise_key_ideas"] = "es"` |
| `tests/` | New tests for the two prompt builders, the extraction helper, and the synthesis gate |
| `CLAUDE.md` | Document the new mode |