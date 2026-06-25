# CLAUDE.md — BookWeaver context for AI assistants

---

## What this project does

BookWeaver is a PyQt6 desktop app.
It reads an English EPUB and produces output via Ollama, using one of three
processing modes:

- **Summarise → Rewrite** — condenses each chapter to a target length (via
  `build_summary_prompt`), then rewrites it in Spanish (via `build_rewrite_prompt`).
- **Full translation** — translates each chapter chunk directly into Spanish
  (via `build_translation_prompt`), preserving the full source text.
- **Summarise only** — condenses each chapter to the target length and saves the
  result as English text; no translation is performed. Uses `build_summary_prompt`.

Chapters longer than the configured chunk size are split at paragraph
boundaries, processed independently, and rejoined.

---

## File map

| File | Purpose | What to touch |
|---|---|---|
| `main.py` | Entry point only | Rarely |
| `app.py` | Main window, UI wiring, slot logic | For new UI elements |
| `epub_io.py` | EPUB → ordered `Chapter` list (titles via TOC→heading→preview); shared by app & worker | For chapter extraction/title logic |
| `worker.py` | Background thread, pipeline, file output (no longer extracts chapters inline — delegates to `epub_io`) | For pipeline changes |
| `prompts.py` | All LLM prompt strings | For prompt tuning |
| `widgets.py` | All reusable Qt widgets | For new/changed widgets |
| `settings.py` | Config loader — reads JSON, builds stylesheet | For loader logic changes |
| `tts.py` | Kokoro TTS → MP3 audiobook with ID3 chapters; optional deps behind an import gate | For TTS/audio changes |
| `bookweaver.json` | All user-editable settings: colours, models, timeout, TTS voices | User edits; no code changes |

---

## Architecture rules

1. **Imports flow one way:**
   `main` → `app` → `worker`, `widgets`, `settings`
   `app` → `epub_io` (lazy, in `_on_epub_selected`)
   `worker` → `prompts`, `settings`, `tts` (lazy, inside `_generate_mp3` only)
   `worker` → `epub_io` (lazy, inside `run`)
   `widgets` → `settings` (only — `ChapterListWidget` stays decoupled from
   `epub_io`; the app passes it plain `(index, label)` pairs)
   `epub_io` → `ebooklib`/`bs4` only; never Qt, `app`, `worker`, or `settings`
   `prompts` → nothing
   `tts` → optional TTS deps only (`kokoro`, `numpy`, `soundfile`, `lameenc`,
   `mutagen`), all behind the `TTS_AVAILABLE` import gate; never Qt, never
   `app`/`worker`
   `settings` → nothing (stdlib only)
   Never import `app` or `worker` from `widgets` or `settings`.
   `app.py` must not import `tts` — it checks Kokoro availability cheaply
   via `importlib.util.find_spec("kokoro")` to avoid loading torch at startup.

2. **All colours come from `bookweaver.json` via `settings.py`.**
   Never hardcode hex values anywhere else.

3. **`SETTINGS` and `OLLAMA_TIMEOUT` are module-level globals in `settings.py`**,
   populated by `_build()` at import time.

4. **`ProcessingWorker` must never import Qt UI classes** — it runs in a
   background thread and communicates only via pyqtSignal.

5. **`prompts.py` has no Qt dependency at all.**

6. **`creativity_to_temperature()` lives in `settings.py`** — single source
   of truth used by both `worker.py` and `widgets.py`.

---

## Configuration system

All user-editable values live in `bookweaver.json`:

- `colors` — hex values for the full colour palette
- `models` — list of `{label, value}` objects for the model dropdown
- `default_model` — value string of the default selection
- `ollama_timeout` — default timeout in seconds (overridable per-run in the UI)
- `chapter_title_preview_chars` — fallback title length (default 50): when a
  chapter has no TOC title or heading, its title is the first N characters of
  its text
- `tts` — MP3 audiobook defaults: `default_voice_es`, `default_voice_en`,
  `mp3_bitrate_kbps`, `inter_chapter_silence_ms`, `post_title_silence_ms`
- `voices` — per-language (`es`/`en`) lists of `{label, value}` Kokoro voices
  for the voice dropdown; adding/removing a voice is a JSON edit, no code change

`settings.py` loads this at import time via `_build()`, which populates all
`C_*` colour constants, builds `STYLESHEET`, populates `SETTINGS`, and sets
`OLLAMA_TIMEOUT`.

---

## Pipeline

### Config keys relevant to the pipeline

| Key | Type | Description |
|---|---|---|
| `mode` | `str` | `"summarise_rewrite"` (default), `"translate"`, or `"summarise_only"` |
| `chunk_size` | `int` | Max words per chunk (default 2 000) |
| `keep_pct` | `int` | Condensation % — used in `summarise_rewrite` and `summarise_only` modes |
| `out_format` | `list[str]` | One or more of `"txt"`, `"epub"`, `"html"` — all selected formats are written |
| `selected_chapters` | `list[int]` | Indices (into the extracted chapter list) the user ticked; the worker processes only these. `None`/absent means all |
| `creativity` | `int` | 1–10 scale; controls temperature and prose directives |
| `level` | `str` | CEFR level: `"B1"`, `"B2"`, `"C1"`, or `"C2"` |
| `generate_mp3` | `bool` | Synthesise an MP3 audiobook after the text output (requires `"txt"` in `out_format` and the optional Kokoro install — see `kokoro.md`) |
| `voice` | `str \| None` | Kokoro voice id (e.g. `"ef_dora"`); `None` when MP3 is off |
| `target_lang` | `str` | `"es"` or `"en"` — from `TARGET_LANG[mode]` in `settings.py`; selects the voice list and Kokoro language |

### Per chapter

1. **Chunk** — if the chapter exceeds `chunk_size` words, `_split_into_chunks()`
   splits it at paragraph boundaries into chunks of at most `chunk_size` words.

2. **Process each chunk** — branched by `mode`:

   - **`summarise_rewrite`** (two LLM calls per chunk):
     - `build_summary_prompt(chunk, keep_pct)` → condensed English
     - `build_rewrite_prompt(summary, level, idx, creativity)` → Spanish chapter text

   - **`translate`** (one LLM call per chunk):
     - `build_translation_prompt(chunk, level, idx, creativity)` → Spanish chapter text

   - **`summarise_only`** (one LLM call per chunk):
     - `build_summary_prompt(chunk, keep_pct)` → condensed English (saved as-is, no rewrite)

3. **Rejoin** — output chunks are joined with `\n\n` into a single chapter result.

4. **Per-chapter file (txt only)** — once a chapter completes, if `"txt"` is in
   `out_format`, its result is also written to
   `{stem}_ES_{level}_chapters/{NN} - {title}.txt` (all modes), where `NN` is
   `index + 1` (the number shown in the UI chapter list). Both this file and the
   assembled `.txt` use the shared `ProcessingWorker._chapter_block` formatter,
   so their per-chapter formatting stays identical. The assembled `.txt` is
   still written normally after all chapters.

### After all chapters (optional MP3)

If `generate_mp3` is set and `"txt"` is among the output formats, the worker
calls `tts.synthesise_book()` on the final `(title, text)` list as the last
step in `run()`, producing `{stem}_ES_{level}.mp3` with ID3v2 CHAP/CTOC
chapter markers. TTS does **not** count toward `total_steps` — it runs after
the progress bar fills and reports via log lines only. An MP3 failure is
logged but never fails the run (text outputs are already written).

### Progress bar

`total_steps = len(chapters) * steps_per_chapter`
where `steps_per_chapter` is **2** in `summarise_rewrite` mode and **1** in
`translate` and `summarise_only` modes. This keeps the progress bar accurate regardless of mode.

The log shows `Chapter 3.1/4`, `3.2/4` etc. when chunking is active.

---

## Resume system

`ProcessingWorker` tracks:
- `completed_results` — list of `(title, text)` tuples updated after each chapter (text is Spanish or English depending on mode)
- `failed_at_chapter` — index of the chapter that failed

On `finished(False)`, if `completed_results` is non-empty, `BookWeaverApp`
stores a `_resume_state` dict and shows a **Resume** button. Pressing it
creates a new worker with `resume_from`, `prior_results`, `timeout`, and
`chunk_size` injected into the config dict. The chapter loop skips
already-done chapters and seeds `results` with the prior work.

`_on_resume` rebuilds the config by spreading the original (`**config`), so
`selected_chapters` rides along automatically — a resumed run reprocesses the
same chapter subset, and `resume_from` indexes into that already-filtered list.

---

## Timeout

`_ollama_call` uses `self._timeout`, set from `config["timeout"]` (UI spinbox
value) falling back to `OLLAMA_TIMEOUT` from `bookweaver.json`.
The default is 1 200 seconds.

**`_ollama_call` has no default for `temperature`** — it must always be passed
explicitly. This is intentional to prevent silent wrong values.

Full translation mode generates more tokens than the summarise pipeline and
may require a higher timeout, especially for large chapters.

---

## Known historical issues

Repeated `str_replace` edits have previously caused `class Foo(Bar):`
declaration lines to be silently dropped.

**After any edit that touches a class boundary, verify with:**

```bash
grep -n "^class " *.py
```

Expected output:

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

---

## Test suite

Tests live in `tests/`. No Qt installation required — `conftest.py` stubs
out PyQt6 at import time.

```bash
pytest           # run all tests
pytest -q        # quiet output
```

Tested modules: `prompts.py`, `settings.py`, `worker.py` (pure functions and
file I/O), `tts.py` (import gate and pure helpers only). The Qt pipeline,
full Ollama integration, and real Kokoro synthesis are not unit-tested —
`conftest.py` also stubs the optional TTS packages (but never `numpy`:
`pytest.approx` inspects `sys.modules["numpy"]` and an empty stub breaks it).

One pre-existing failure exists in `test_settings.py::TestOllamaTimeout::test_defaults_when_missing`
— the test asserts a default of `600` but `settings.py` has always defaulted
to `1200`. This is not related to any recent changes.

---

## Adding a new UI control

1. Add the widget to `widgets.py` if reusable, or inline in `app.py`.
2. Add the field to `_build_config()` in `app.py`.
3. Pass it through in the resume config block in `_on_resume()` if it should be re-applied on resume.
4. Extract the value in `worker.py`'s `run()` method.
5. Pass it to the appropriate prompt builder in `prompts.py` if relevant.

---

## Adding a new output format

1. Add a `QCheckBox` in `app.py → _add_options_group()` and include it in the `out_fmt` list comprehension in `_build_config()`.
2. Add a `_write_xxx()` method in `worker.py` — accept `lang_label` as a parameter so the output header reflects the actual language/mode.
3. Add the branch in `worker.py → run()` after `# ── write output ──`.

---

## Adding a new processing mode

1. Add a radio button to the Processing mode group in `app.py → _add_summarisation_group()`.
2. Wire any show/hide logic to `_on_mode_changed()` in `app.py`.
3. Add the mode string to `_build_config()`.
4. Add the prompt builder function to `prompts.py`.
5. Add the branch inside the chunk loop in `worker.py → run()`.
6. Adjust `steps_per_chapter` in `worker.py` if the number of LLM calls per chunk differs.

---

## Prompt tuning

All LLM instructions live in `prompts.py`:

- `_LEVEL_GUIDANCE` — per-CEFR-level Spanish writing instructions (shared by all modes)
- `_creativity_instruction()` — maps creativity 1–10 to prose directives (shared by all modes)
- `build_summary_prompt()` — condensation prompt (word-count-target driven); used by summarise → rewrite and summarise-only modes
- `build_rewrite_prompt()` — Spanish rewrite prompt; used by summarise → rewrite only
- `build_translation_prompt()` — direct translation prompt; used by full translation mode only

**Important:** `build_summary_prompt` frames the task as "condense to N words"
rather than "summarise" — LLMs treat "summarise" as a signal to produce short
output regardless of any percentage instruction.

---

## PEP 8 notes

- `E221` (aligned assignments) is suppressed — intentional for colour/config blocks.
- Max line length is 100.
- Run `pycodestyle --statistics *.py` to check.
