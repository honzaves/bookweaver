# Kokoro TTS — MP3 audiobook output

Design for adding Kokoro-powered MP3 audiobook generation to BookWeaver.
The feature is **strictly additive**: when its checkbox is off, the existing
pipeline runs unchanged.

---

## 1. Goals & non-goals

**Goals**

- Generate one `.mp3` audiobook per book run, with ID3v2 chapter markers,
  produced **locally** via Kokoro after the text pipeline finishes.
- Voice dropdown driven by the target language of the selected processing
  mode (Spanish for `summarise_rewrite` / `translate`, English for
  `summarise_only`).
- MP3 option is gated on the plain-text (`.txt`) output checkbox.
- Optional install — base BookWeaver users who never enable MP3 must not be
  forced to download the ~2.5 GB PyTorch + model bundle.

**Non-goals**

- Streaming/playback inside the app.
- Per-chapter `.mp3` files (single concatenated file with chapter markers
  is the chosen shape).
- Resumable TTS — if a run is resumed, MP3 is generated once at the end
  from the final `completed_results`. Audio is **not** cached between
  runs.
- Voice cloning, fine-tuning, or custom prosody control.

---

## 2. Decision summary

| Decision | Choice | Rationale |
|---|---|---|
| TTS implementation | `kokoro` PyPI (PyTorch + MPS) | Active upstream, best voice coverage, Apple Silicon GPU via MPS. |
| Output shape | 1 MP3 / book + ID3 CHAP/CTOC frames | Matches user requirement, supports podcast/audiobook player navigation. |
| Mode scope | All modes that produce `.txt` | Voice list switches by target language. |
| Resume | Re-generate from scratch | Simplest; no extra state to track. |
| Chapter title spoken? | **Yes**, at start of each chapter, followed by ~1 s silence | Audiobook convention; gives audible structure beyond ID3 markers (not all players surface them). |
| MP3 encoder | `lameenc` (pure pip wheel) | No ffmpeg system dependency. |
| Chapter markers | `mutagen` (ID3v2 CHAP + CTOC frames) | Standard, well-supported. |
| Install posture | Optional extra | Base app must keep working without Kokoro installed. |
| New module | `tts.py` — pure synthesis + encode, no Qt | Mirrors `prompts.py` / `settings.py` boundary. |

### Open decisions to revisit later

- Speak chapter title in **source** language (English) even in Spanish
  modes, or in the target language? Recommend: speak the title verbatim
  as it appears in `completed_results` (which is `Capítulo N` for Spanish
  modes, `Chapter N` for summarise-only). Kokoro handles both cleanly.

---

## 3. Installing Kokoro on macOS

This section is what a human reader (or Claude) follows to get a working
TTS environment. The app code in §5 detects missing pieces and surfaces
clear errors.

### 3.1 System dependencies

```bash
# Homebrew is assumed to be installed.

# Required for Spanish voices (misaki uses espeak-ng for es G2P).
# Not required for English voices.
brew install espeak-ng
```

> If only English summarisation will ever be used (i.e. `summarise_only`
> mode), `espeak-ng` can be skipped. The app should still warn at first
> Spanish-voice use if it is missing.

### 3.2 Python dependencies

Create `requirements-tts.txt` (sibling to `requirements.txt`):

```
kokoro>=0.9
soundfile>=0.12
lameenc>=1.7
mutagen>=1.47
en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

`torch` is pulled in transitively by `kokoro`. On macOS the standard
PyPI wheel includes the MPS backend automatically; no special index URL
is needed.

> **Why the spaCy model wheel?** English voices use misaki's English G2P,
> which auto-downloads `en_core_web_sm` via `pip` on first use — and calls
> `sys.exit(1)` if that fails. Venvs created by `uv` have no pip, so the
> auto-download dies. Installing the model wheel explicitly avoids this.
> (`tts.py` also traps the `SystemExit` and surfaces a readable error.)

Install with:

```bash
pip install -r requirements-tts.txt
```

Expect ~2.5 GB after first model fetch. Kokoro auto-downloads weights
from Hugging Face on first `KPipeline(...)` call into
`~/.cache/huggingface/`.

### 3.3 Smoke test

After install, verify from a Python REPL:

```python
from kokoro import KPipeline
import soundfile as sf
pipe = KPipeline(lang_code="a")          # American English
gen = pipe("Hello world.", voice="af_heart")
for i, (gs, ps, audio) in enumerate(gen):
    sf.write(f"hello_{i}.wav", audio, 24000)
```

If this writes a playable `hello_0.wav`, the install is good.

For Spanish:

```python
pipe = KPipeline(lang_code="e")          # Spanish (requires espeak-ng)
gen = pipe("Hola, mundo.", voice="ef_dora")
```

### 3.4 README update

Add a short "Optional: MP3 audiobook output" section to `README.md`
that links to this file for full instructions.

---

## 4. Architecture & file map updates

### 4.1 New file

| File | Purpose | Imports |
|---|---|---|
| `tts.py` | Synthesise text → audio bytes, encode MP3, embed ID3 chapters. Pure functions; no Qt. | `kokoro`, `numpy`, `soundfile`, `lameenc`, `mutagen` (all guarded) |

### 4.2 Updated import rules (extend §"Architecture rules" in CLAUDE.md)

```
main → app → worker, widgets, settings
worker → prompts, settings, tts
widgets → settings
prompts → nothing
tts → settings (read-only, for voice list); never Qt
settings → nothing
```

`tts.py` must never import Qt, never call back into `worker`/`app`.
The worker hands it a list of `(title, body)` tuples and an output path,
and gets back a written file (or raises).

### 4.3 Optional-import gate

At the top of `tts.py`:

```python
try:
    import kokoro
    import soundfile
    import lameenc
    import mutagen
    TTS_AVAILABLE = True
    TTS_IMPORT_ERROR: Exception | None = None
except ImportError as exc:
    TTS_AVAILABLE = False
    TTS_IMPORT_ERROR = exc
```

Consumers check `TTS_AVAILABLE` before calling any synth function.

---

## 5. Config (`bookweaver.json`)

Add a `voices` block keyed by language code matching the target
language of each processing mode:

```jsonc
{
  // ...existing keys...
  "tts": {
    "default_voice_es": "ef_dora",
    "default_voice_en": "af_heart",
    "mp3_bitrate_kbps": 96,
    "inter_chapter_silence_ms": 1500,
    "post_title_silence_ms": 1000
  },
  "voices": {
    "es": [
      { "label": "Dora (female)",   "value": "ef_dora"  },
      { "label": "Alex (male)",     "value": "em_alex"  },
      { "label": "Santa (male)",    "value": "em_santa" }
    ],
    "en": [
      { "label": "Heart (female, US)",  "value": "af_heart"   },
      { "label": "Bella (female, US)",  "value": "af_bella"   },
      { "label": "Michael (male, US)",  "value": "am_michael" },
      { "label": "Emma (female, UK)",   "value": "bf_emma"    },
      { "label": "George (male, UK)",   "value": "bm_george"  }
    ]
  }
}
```

`settings.py::_build()` extends `SETTINGS` with `voices` and `tts`
blocks, and exposes a helper:

```python
def voices_for_language(lang_code: str) -> list[dict]:
    """Return the configured voice list for a 2-letter language code."""
    return SETTINGS.get("voices", {}).get(lang_code, [])
```

Mode → language code mapping (computed in `app.py`):

```python
TARGET_LANG = {
    "summarise_rewrite": "es",
    "translate":         "es",
    "summarise_only":    "en",
}
```

---

## 6. UI design (`app.py`, `widgets.py`)

### 6.1 New controls in `_add_options_group`

Inserted after the existing output-format row, before the output-folder
row:

```
[ ] Generate MP3 audiobook  (Kokoro TTS)
    Voice: [ Dora (female) ▾ ]
```

- Checkbox: `self._mp3_chk` — disabled and unchecked when `self._fmt_txt`
  is unchecked. Tooltip on the disabled state: "Enable plain-text output
  to use MP3 audiobook generation."
- Voice dropdown: `self._voice_combo` — visible only when `self._mp3_chk`
  is checked. Items rebuilt from `voices_for_language(TARGET_LANG[mode])`
  whenever the mode changes.

### 6.2 Wiring rules

| Trigger | Effect |
|---|---|
| `self._fmt_txt.toggled` | If unchecked: uncheck and disable `self._mp3_chk`, hide voice dropdown. If checked: enable `self._mp3_chk`. |
| `self._mp3_chk.toggled` | Show/hide voice dropdown. |
| `self._on_mode_changed` | Rebuild voice dropdown contents from `voices_for_language(TARGET_LANG[mode])`. Preserve current selection if still present, else fall back to `default_voice_es` / `default_voice_en`. |
| First load with no Kokoro installed | Checkbox disabled with tooltip: "Install Kokoro to enable MP3 output — see kokoro.md." |

### 6.3 Config dict additions (`_build_config`)

```python
"generate_mp3": self._mp3_chk.isChecked(),
"voice":        self._voice_combo.currentData() if self._mp3_chk.isChecked() else None,
"target_lang":  TARGET_LANG[mode],
```

### 6.4 Resume

`_on_resume` already forwards the original `config`. The MP3 settings
flow through unchanged.

---

## 7. Pipeline integration (`worker.py`)

MP3 generation is the **last** step in `run()`, after all chapter
writers complete. It reads `completed_results` (the in-memory list of
`(title, body)` tuples) — **not** any written file.

### 7.1 Hook location

```python
# ── write output ──────────────────────────────────────
out_folder.mkdir(parents=True, exist_ok=True)
# ... existing txt/epub/html writers ...

# ── MP3 audiobook (optional) ──────────────────────────
if cfg.get("generate_mp3") and "txt" in out_format:
    self._generate_mp3(results, out_folder, stem, level, meta, cfg)
```

The guard `"txt" in out_format` is defensive — the UI already prevents
this combination — but kept so the worker is correct in isolation.

### 7.2 `_generate_mp3` outline

```python
def _generate_mp3(self, results, out_folder, stem, level, meta, cfg):
    from tts import TTS_AVAILABLE, TTS_IMPORT_ERROR, synthesise_book

    if not TTS_AVAILABLE:
        self.log.emit(
            f"MP3 requested but Kokoro is not installed "
            f"({TTS_IMPORT_ERROR}). See kokoro.md.", "error",
        )
        return

    voice = cfg["voice"]
    lang_code = cfg["target_lang"]
    out_path = out_folder / f"{stem}_ES_{level}.mp3"

    self.log.emit(
        f"\n🔊  Synthesising audiobook with voice '{voice}'…", "info",
    )
    try:
        synthesise_book(
            chapters=results,
            voice=voice,
            lang_code=lang_code,
            out_path=out_path,
            bitrate_kbps=...,
            inter_chapter_silence_ms=...,
            post_title_silence_ms=...,
            book_title=meta["title"],
            author=meta["creator"],
            on_chapter=lambda i, n: self.log.emit(
                f"   ↳ Chapter {i}/{n} synthesised.", "muted"
            ),
        )
        self.log.emit(f"🎧  Saved MP3 → {out_path}", "success")
    except Exception as exc:
        self.log.emit(f"MP3 generation failed: {exc}", "error")
```

### 7.3 Progress bar

To keep the existing progress bar accurate, **TTS does not count toward
`total_steps`**. It happens after the bar fills, and its progress is
reported via log lines only. (A future enhancement could add a second
phase; out of scope here.)

---

## 8. `tts.py` — synthesis & MP3 encoding

### 8.1 Public surface

```python
def synthesise_book(
    *,
    chapters: list[tuple[str, str]],   # (title, body) pairs
    voice: str,
    lang_code: str,                    # "e" for Spanish, "a" for English (US)
    out_path: Path,
    bitrate_kbps: int = 96,
    inter_chapter_silence_ms: int = 1500,
    post_title_silence_ms: int = 1000,
    book_title: str = "",
    author: str = "",
    on_chapter: Callable[[int, int], None] | None = None,
) -> None:
    """Synthesise all chapters into a single MP3 with ID3 chapter markers."""
```

`lang_code` mapping for Kokoro:

| `target_lang` in config | Kokoro `lang_code` |
|---|---|
| `es` | `"e"` |
| `en` | `"a"` (American voices; UK voices use `"b"` — detect from voice prefix `bf_`/`bm_`) |

### 8.2 Synthesis loop

`KPipeline(text, voice=...)` is a **generator** that yields
`(graphemes, phonemes, audio_chunk)` tuples — it auto-segments long
text at ~510 tokens. The audio chunk is a 1-D `numpy.float32` array at
**24 000 Hz**. Per chapter:

```python
pipe = KPipeline(lang_code=lang_code)

def synth(text: str) -> np.ndarray:
    parts = [audio for _, _, audio in pipe(text, voice=voice)]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
```

Then for each chapter:

```python
title_audio   = synth(title)
title_silence = silence(post_title_silence_ms, sr=24000)
body_audio    = synth(body)
chap_audio    = np.concatenate([title_audio, title_silence, body_audio])
```

Chapters are joined with `silence(inter_chapter_silence_ms)`. As each
chapter is appended, record its **start sample offset** for ID3 markers
(converted to ms = `samples * 1000 // 24000`).

### 8.3 MP3 encoding via `lameenc`

```python
import lameenc

def encode_mp3(audio_f32: np.ndarray, sr: int, bitrate_kbps: int) -> bytes:
    enc = lameenc.Encoder()
    enc.set_bit_rate(bitrate_kbps)
    enc.set_in_sample_rate(sr)
    enc.set_channels(1)
    enc.set_quality(2)  # 0 = best, 9 = worst
    pcm16 = (np.clip(audio_f32, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    return enc.encode(pcm16) + enc.flush()
```

Write the bytes to `out_path` before tagging.

### 8.4 ID3 chapter markers with `mutagen`

```python
from mutagen.id3 import ID3, CHAP, CTOC, TIT2, TPE1, TALB, CTOCFlags

tags = ID3()
if book_title: tags.add(TIT2(encoding=3, text=book_title))
if author:     tags.add(TPE1(encoding=3, text=author))
tags.add(TALB(encoding=3, text=book_title or "BookWeaver audiobook"))

child_ids = []
for i, (title, start_ms, end_ms) in enumerate(chapter_offsets):
    cid = f"ch{i+1}"
    child_ids.append(cid)
    tags.add(CHAP(
        element_id=cid,
        start_time=start_ms,
        end_time=end_ms,
        start_offset=0xFFFFFFFF,
        end_offset=0xFFFFFFFF,
        sub_frames=[TIT2(encoding=3, text=title)],
    ))
tags.add(CTOC(
    element_id="toc",
    flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
    child_element_ids=child_ids,
    sub_frames=[TIT2(encoding=3, text="Chapters")],
))
tags.save(str(out_path))
```

The `start_ms`/`end_ms` values come from the per-chapter sample offsets
recorded in §8.2.

### 8.5 Error handling

`synthesise_book` raises on any failure. The worker catches and logs;
the rest of the run (already-saved txt/epub/html) is not affected.

A specific case worth its own message: when `lang_code="e"` and
`espeak-ng` is missing, misaki raises a clear error — re-raise it with
a hint to run `brew install espeak-ng`.

---

## 9. Tests

`tests/conftest.py` currently stubs PyQt6. Extend it to stub the
heavier TTS deps so the existing test suite keeps passing on machines
without Kokoro installed:

```python
# conftest.py additions
import sys, types
for name in ("kokoro", "soundfile", "lameenc", "mutagen", "mutagen.id3",
             "torch", "numpy"):
    sys.modules.setdefault(name, types.ModuleType(name))
```

> Stubbing `numpy` is only acceptable because no existing test imports
> it. If a future test needs real numpy, drop that line.

New tests (`tests/test_tts.py`):

- `test_tts_import_gate_when_kokoro_missing` — patches sys.modules to
  remove `kokoro`, reloads `tts`, asserts `TTS_AVAILABLE is False`.
- `test_target_lang_mapping` — covers `summarise_rewrite → es`,
  `translate → es`, `summarise_only → en`.
- `test_voices_for_language_from_settings` — asserts the config-driven
  voice list is exposed correctly.
- `test_lang_code_mapping_uk_voices` — `bf_*` / `bm_*` voices map to
  `lang_code="b"`, others to `"a"` for English.

Real Kokoro synthesis is **not** unit-tested (slow, GB download). A
manual smoke test in §3.3 covers it.

---

## 10. Phased delivery

Each phase ends in a usable state. Phases 1–4 can ship together for a
v0 release; 5–6 are polish.

### Phase 1 — dependency plumbing & install docs *(this design + 1 file)*

- Add `requirements-tts.txt`.
- Add the "Optional: MP3 audiobook output" section to `README.md`
  pointing at `kokoro.md`.
- No code changes; existing app fully functional.

### Phase 2 — `tts.py` skeleton with optional-import gate

- Create `tts.py` with the import gate and a single function
  `synthesise_chapter(text, voice, lang_code) -> np.ndarray`.
- Add `tts.py` to the CLAUDE.md file map + architecture rules.
- Extend `tests/conftest.py` stubs. Add `test_tts_import_gate_when_kokoro_missing`.

### Phase 3 — chapter concatenation → single MP3 (no chapter markers)

- Implement `synthesise_book` end-to-end **without** ID3 chapters.
- Encode via `lameenc`, write raw MP3.
- Worker hook `_generate_mp3` calls it; voice/lang hardcoded for first
  manual test.

### Phase 4 — UI: checkbox, voice dropdown, txt-gating, mode wiring

- Add config keys `voices` and `tts` to `bookweaver.json`.
- Add `voices_for_language` helper to `settings.py`.
- Add `TARGET_LANG` map and `_mp3_chk` / `_voice_combo` controls in
  `app.py`.
- Wire `_fmt_txt.toggled` and `_on_mode_changed` per §6.2.
- Pass `generate_mp3`, `voice`, `target_lang` through `_build_config`.
- Worker reads them from cfg instead of the hardcoded values from
  Phase 3.

### Phase 5 — ID3 CHAP / CTOC chapter markers

- Record per-chapter sample offsets during synthesis.
- Add `mutagen` tagging step after MP3 write.
- Verify with at least one podcast/audiobook player (e.g. Apple
  Podcasts, AntennaPod, VLC chapter list).

### Phase 6 — polish

- `on_chapter` callback wired to worker `log` signal for per-chapter
  progress lines.
- Re-do disabled-state tooltip on the MP3 checkbox to reflect actual
  cause (txt unchecked vs. Kokoro not installed).
- Update CLAUDE.md with the new file, architecture rule, and config
  keys.
- Add the `test_target_lang_mapping`, `test_voices_for_language_from_settings`,
  and `test_lang_code_mapping_uk_voices` tests.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| PyTorch wheel size scares users away from base install. | Optional `requirements-tts.txt`; checkbox disabled with clear tooltip when missing. |
| First synthesis blocks the worker thread for tens of seconds while model downloads. | Log a "fetching Kokoro model from Hugging Face…" line before the first `KPipeline()` call; consider caching the pipeline on the worker instance for reuse across chapters. |
| Spanish synthesis silently fails without `espeak-ng`. | Catch the misaki error and surface `brew install espeak-ng` hint in the log. |
| Long books → multi-GB int16 PCM in memory before encode. | At ~24 kHz mono, a 10-hour book is ~1.7 GB int16 — acceptable on modern Macs. If users hit this, switch to streaming `lameenc.encode()` chapter by chapter (the encoder supports it). |
| MPS backend instability on older macOS. | Document minimum macOS 13.3 (PyTorch MPS stable). Fall back to CPU automatically (PyTorch handles via env var `PYTORCH_ENABLE_MPS_FALLBACK=1`). |
| Voice list in `bookweaver.json` drifts from upstream Kokoro releases. | Voices live in config only — adding/removing a voice is a JSON edit, no code change. |

---

## 12. Non-breakage checklist

Before any phase merges, verify:

1. `pytest -q` passes with **only** base requirements installed (no
   `kokoro`, no `torch`).
2. App launches and runs an existing summarise→rewrite job to txt/epub/html
   with MP3 checkbox **unchecked** — output identical to current behaviour.
3. With MP3 checkbox unchecked, the worker never imports `tts` (lazy
   import inside `_generate_mp3`).
4. `grep -n "^class " *.py` matches the expected list in CLAUDE.md
   (per the historical-issues warning).