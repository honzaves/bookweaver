# TTS text sanitization — design

**Date:** 2026-06-29
**Status:** Approved

## Problem

Footnote markers, emphasis asterisks, markdown bullets, and scene-break
separators are fine in the written `.txt`/`.epub`/`.html` output but sound
wrong when spoken by Kokoro: `[3]` is read as "three", `* * *` makes odd
noises, leading `*`/`-` bullets get vocalized.

## Goal

Sanitize the text fed to Kokoro **without** altering any written text output.

## Isolation guarantee

All cleaning happens inside `tts.py` on local strings. The `results` list
(`list[(title, body)]`) is shared with the `.txt`/`.epub`/`.html` writers and
is **never mutated**. Text outputs keep footnotes/asterisks; only the audio is
cleaned.

## Components

### `clean_for_tts(text: str) -> str` (pure helper)

Inline cleanup, applied in this order (order matters):

1. Strip footnote refs: `[12]` (bracketed digits), `(12)` (parenthetical
   digits), and superscript runs `¹²³⁴…` (`¹²³⁰-⁹`).
2. Strip leading bullet markers per line: `^\s*[-*+•]\s+` → keep the content.
3. Remove emphasis chars: all `*` and backticks; underscores only at a word
   boundary (`_word_` → `word`, but `snake_case` is left intact).
4. Normalize whitespace: collapse multi-spaces, trim line ends, collapse 3+
   blank lines to one.

### `segments_for_tts(body: str) -> list[str]` (pure helper)

Scene-break splitting:

- Splits `body` on lines matching `^\s*([*\-_]\s*){3,}$` (catches `* * *`,
  `***`, `---`, `___`, `- - -`).
- Splits **first**, then runs `clean_for_tts` on each part, so scene-break
  asterisks are not eaten by `clean_for_tts` step 3.
- Drops empty parts.
- No scene breaks → returns a single-element list → byte-identical to today's
  behavior.

### `synthesise_book` changes

- New param `scene_break_silence_ms: int = 800`.
- Title: `_synth(pipe, clean_for_tts(title), ...)`.
- Body: replace the single body `_synth` with a loop over
  `segments_for_tts(body)`, interleaving `_silence(scene_break_silence_ms)`
  between parts. `cursor` / `chapter_offsets` accounting is unchanged — silence
  is appended to `segments` like any other segment.

## Config

Add `"scene_break_silence_ms": 800` to the `tts` block in `bookweaver.json`.
`_generate_mp3` (`worker.py`) passes
`tts_cfg.get("scene_break_silence_ms", 800)`. The default in code means a
missing key never breaks.

## Testing

`tests/test_tts.py` (no Kokoro needed):

- `clean_for_tts`: each marker type, snake_case preserved, leading bullets,
  idempotency.
- `segments_for_tts`: each scene-break form, no-break passthrough, empty-part
  dropping, and that `* * *` survives the split (ordering correctness).

## Scope

~40 lines of helpers + a small loop edit in `synthesise_book` + one config key
+ tests. No new files. tts.py stays pure-no-Qt.
