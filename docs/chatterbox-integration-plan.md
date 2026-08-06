# Adding Chatterbox TTS to BookWeaver — implementation plan

**Audience:** a coding agent working in `/Users/jan/Projects/bookweaver`.
**Goal:** offer a choice of TTS engine — Kokoro (existing) or **Chatterbox (new, default)** —
and produce an audiobook from text using Chatterbox voice cloning.

Read `CLAUDE.md` first. Its **Architecture rules** (§51) are binding: `tts.py` must stay
Qt-free and import optional TTS deps only, behind availability gates; `worker.py` imports
`tts` lazily inside `_generate_mp3` only; `app.py` must never import `tts`.

---

## 0. What Chatterbox is, and why it changes assumptions

Chatterbox (`mlx-community/chatterbox-multilingual-v3`, 2.7 GB) is a **voice cloning**
model, not a voice-library model. Four consequences drive this whole plan:

1. **There is no built-in voice.** The multilingual weights ship no `conds.safetensors`.
   Without a reference audio clip, generation raises `ValueError`. A reference clip is a
   **required input**, not an option. This is why the UI needs a new field.
2. **It does not stream.** `stream` is documented as ignored
   (`mlx_audio/tts/models/chatterbox/chatterbox.py:804`); a 292-character paragraph
   returns as a *single* chunk after ~10s. Progress and cancellation must therefore come
   from *our* chunking, not from the model.
3. **Accent follows the clip, not the language code.** There is one `"es"` language code;
   Castilian vs Latin American is decided by whose voice you clone. Cross-lingual cloning
   works — an English speaker's clip produces good Spanish.
4. **Output is mono 24 kHz float32** — identical to Kokoro's `SAMPLE_RATE`, so the
   existing encode/tag path needs no resampling.

Useful measurements (Apple Silicon, warm): model load **2.4s** (first ever load ~171s, it
also fetches `mlx-community/S3TokenizerV2`); generation roughly **2× faster than real
time**.

---

## 1. ⚠️ Do this first: verify MLX works in BookWeaver's worker thread

**This is the highest risk in the whole task. Do not skip it, and do not build on top of
it until it is settled.**

`ProcessingWorker` runs in a background `QThread`. In a sibling project, MLX TTS
generation on a non-main thread produced **degraded and unseedable** output: MLX arrays
and streams are thread-affine, and a worker thread gets a different stream
(`Stream(gpu,0)` vs `Stream(gpu,2)`). Symptoms observed there with a different MLX TTS
model:

- identical parameters gave 5.44s of speech on the main thread and 20.48s of rambling on
  a worker thread
- with **no seeding at all**, the main thread produced five different durations across
  five runs while the worker produced the *same* duration five times — randomness never
  reached the sampler
- loading the model *in* the worker thread did not help
- pinning the worker to the main thread's stream is impossible:
  `RuntimeError: There is no Stream(gpu, 0) in current thread`

This was never verified for Chatterbox specifically. **Verify it before designing around
it**, with a standalone script (no Qt):

```python
# scripts/check_mlx_thread_affinity.py
import threading
from pathlib import Path
from mlx_audio.tts.utils import load_model

REF = Path("references/narrator_en.wav")   # any 10-20s clean speech clip
TEXT = "The morning light came slowly through the tall windows."
model = load_model("mlx-community/chatterbox-multilingual-v3")

def run(label):
    import mlx.core as mx
    for seed in (1, 2, 3):
        mx.random.seed(seed)
        out = list(model.generate(text=TEXT, ref_audio=str(REF), lang_code="en"))
        n = sum(int(r.audio.shape[0]) for r in out)
        print(f"{label:14s} seed={seed} samples={n}")

run("main thread")
t = threading.Thread(target=run, args=("worker thread",)); t.start(); t.join()
```

**Interpretation:**

- *Worker-thread sample counts vary by seed and are in the same range as the main
  thread's* → MLX is fine on threads here. Proceed with the straightforward plan
  (§2–§8), synthesising inside `ProcessingWorker` as Kokoro does today.
- *Worker-thread counts are identical across seeds, or wildly different from main* →
  **MLX generation is broken off the main thread.** Do not synthesise in
  `ProcessingWorker`. Use the subprocess variant in **§9** instead, and tell the user
  before writing code, since it is a larger change.

---

## 2. Dependencies — split per engine

Kokoro pulls torch (~2.5 GB); Chatterbox uses MLX. Nobody should install both to use one.

Replace `requirements-tts.txt` with three files:

**`requirements-tts-common.txt`** — shared encode/tag stack
```
soundfile>=0.12
lameenc>=1.7
mutagen>=1.47
numpy>=1.26
```

**`requirements-tts-kokoro.txt`**
```
-r requirements-tts-common.txt
kokoro>=0.9
# English voices need this spaCy model; misaki's auto-download dies in pip-less venvs.
en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```
Spanish additionally needs `brew install espeak-ng` (unchanged, see `kokoro.md`).

**`requirements-tts-chatterbox.txt`**
```
-r requirements-tts-common.txt
mlx-audio>=0.4.7
```
No espeak-ng, no spaCy, no torch.

Keep `requirements-tts.txt` as a one-line pointer to both, so existing instructions do not
dangle.

---

## 3. `tts.py` — per-engine gates and dispatch

`tts.py` currently has a single `TTS_AVAILABLE` gate for Kokoro. Generalise it, **keeping
every pure helper as-is** — `clean_for_tts`, `segments_for_tts`, `_silence`, `encode_mp3`,
`_tag_mp3` and the scene-break logic are engine-agnostic and must be reused unchanged.

### 3.1 Availability gates

Replace the single `try: import kokoro` block with two independent gates:

```python
ENGINES = ("chatterbox", "kokoro")
DEFAULT_ENGINE = "chatterbox"

try:
    import numpy, soundfile, lameenc, mutagen        # noqa: F401  (shared)
    _COMMON_AVAILABLE, _COMMON_ERROR = True, None
except ImportError as exc:
    _COMMON_AVAILABLE, _COMMON_ERROR = False, exc

try:
    import kokoro                                     # noqa: F401
    KOKORO_AVAILABLE, KOKORO_IMPORT_ERROR = _COMMON_AVAILABLE, _COMMON_ERROR
except ImportError as exc:
    KOKORO_AVAILABLE, KOKORO_IMPORT_ERROR = False, exc

try:
    import mlx_audio                                  # noqa: F401
    CHATTERBOX_AVAILABLE, CHATTERBOX_IMPORT_ERROR = _COMMON_AVAILABLE, _COMMON_ERROR
except ImportError as exc:
    CHATTERBOX_AVAILABLE, CHATTERBOX_IMPORT_ERROR = False, exc


def engine_available(engine: str) -> tuple[bool, Exception | None]:
    """(is_available, import_error) for 'kokoro' or 'chatterbox'."""
```

Keep `TTS_AVAILABLE = KOKORO_AVAILABLE or CHATTERBOX_AVAILABLE` so nothing breaks while
you migrate call sites.

**Do not** move the `HF_HOME` default (`tts.py:28`) — Chatterbox weights should land in
the same project-local `.hf_cache/` as Kokoro's. Note in the docstring that this now
holds ~2.7 GB more.

### 3.2 Language code

BookWeaver already uses 2-letter codes (`"es"`, `"en"`), which match Chatterbox's own
codes, so the mapping is near-identity — but validate rather than pass through blindly:

```python
CHATTERBOX_LANGS = {"ar","da","de","el","en","es","fi","fr","he","hi","it","ja",
                    "ko","ms","nl","no","pl","pt","ru","sv","sw","tr","zh"}

def chatterbox_lang_code(target_lang: str) -> str:
    code = (target_lang or "en").lower()[:2]
    if code not in CHATTERBOX_LANGS:
        raise ValueError(f"Chatterbox does not support language {code!r}")
    return code
```

Leave `kokoro_lang_code()` untouched.

### 3.3 Sentence splitting — new pure helper

Chatterbox cannot stream and drifts over long input, so **we** must chunk. This is a pure
function; unit-test it.

```python
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")

def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Split *text* into sentence-sized pieces for synthesis.

    Chatterbox degrades and eventually truncates on long input, so each piece is
    generated separately and the audio concatenated. Sentences longer than
    *max_chars* are split further at clause boundaries (', ', '; ', ' — ') and, as a
    last resort, on whitespace, so no single call is oversized.
    """
```

Requirements it must satisfy (write these as tests first):
- an empty or whitespace-only string yields `[]`
- abbreviations should not be over-split aggressively — accept `"Mr. Smith"` splitting as
  a known limitation rather than pulling in a heavyweight NLP dependency
- every returned piece is non-empty and `<= max_chars` unless it is a single unbroken word
- joining the pieces with a space reproduces the input's words in order

### 3.4 Chatterbox synthesis

```python
def _load_chatterbox(model_id: str):
    from mlx_audio.tts.utils import load_model
    return load_model(model_id)


def _synth_chatterbox(model, text, *, ref_audio, lang_code, seed,
                      sentence_gap_ms, exaggeration, cfg_weight, temperature,
                      on_sentence=None):
    """Synthesise *text* sentence by sentence and return one float32 array."""
```

Rules:
- iterate `split_sentences(text)`; call `model.generate(...)` per sentence with
  `ref_audio=str(reference_clip)`, `lang_code=lang_code`, and the sampling params
- **set `mx.random.seed(seed)` once before the loop, not per sentence** — a fixed seed
  keeps the delivery stable across a chapter; re-seeding identically per sentence makes
  every sentence share a prosody contour and sounds robotic
- insert `_silence(sentence_gap_ms)` **between** sentences (default 150 ms), not after the
  last one
- convert each result to numpy on the thread that produced it — MLX arrays are
  thread-affine; `np.array(mx_array.tolist(), dtype=np.float32)` after `mx.eval(...)`
- call `on_sentence(done, total)` so the wizard log can show progress within a chapter;
  without it a long chapter looks frozen

### 3.5 Extend `synthesise_book`

Keep the signature backwards-compatible; add keyword-only parameters with defaults:

```python
def synthesise_book(
    *,
    chapters, voice, lang_code, out_path,
    engine: str = DEFAULT_ENGINE,
    reference_clip: Path | str | None = None,
    target_lang: str = "en",
    chatterbox_model: str = "mlx-community/chatterbox-multilingual-v3",
    chatterbox_seed: int = 7,
    sentence_gap_ms: int = 150,
    exaggeration: float = 0.1,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    bitrate_kbps=96, inter_chapter_silence_ms=1500,
    post_title_silence_ms=1000, scene_break_silence_ms=800,
    book_title="", author="",
    on_chapter=None, on_sentence=None,
) -> None:
```

Only the *synthesis call* differs by engine. Keep the existing chapter loop, silences,
offset bookkeeping, `encode_mp3` and `_tag_mp3` exactly as they are — build a small
`synth(text) -> np.ndarray` closure at the top and use it for both title and body parts:

```python
if engine == "chatterbox":
    if not reference_clip:
        raise RuntimeError("Chatterbox needs a reference voice clip …")
    if not Path(reference_clip).exists():
        raise RuntimeError(f"Reference clip not found: {reference_clip}")
    model = _load_chatterbox(chatterbox_model)
    code = chatterbox_lang_code(target_lang)
    synth = lambda t: _synth_chatterbox(model, t, ref_audio=reference_clip, …)
else:
    pipe = _make_pipeline(lang_code)
    synth = lambda t: _synth(pipe, t, voice, lang_code)
```

Validate the reference clip **before** loading the 2.7 GB model, so a typo fails in
milliseconds rather than after a long load.

---

## 4. `bookweaver.json` — config

Extend the `tts` block and add a `reference_voices` block mirroring the existing `voices`
pattern (CLAUDE.md §92: all user-editable values live here):

```json
"tts": {
  "engine": "chatterbox",
  "default_voice_es": "ef_dora",
  "default_voice_en": "af_heart",
  "mp3_bitrate_kbps": 96,
  "inter_chapter_silence_ms": 1500,
  "post_title_silence_ms": 1000,
  "scene_break_silence_ms": 800,

  "chatterbox_model": "mlx-community/chatterbox-multilingual-v3",
  "chatterbox_seed": 7,
  "sentence_gap_ms": 150,
  "chatterbox_exaggeration": 0.1,
  "chatterbox_cfg_weight": 0.5,
  "chatterbox_temperature": 0.8
},

"reference_voices": {
  "es": [
    { "label": "Narrator (Castilian female)", "value": "references/es_castilian_f.wav" }
  ],
  "en": [
    { "label": "Narrator (British male)",     "value": "references/en_british_m.wav" }
  ]
}
```

Keep `exaggeration` low (0.1) for narration — it compounds unpleasantly over hours.

Paths are relative to the project root; resolve them against it, and leave absolute paths
untouched so Browse-selected files work.

---

## 5. `settings.py`

Add, mirroring `voices_for_language()` (`settings.py:295`):

```python
def reference_voices_for_language(lang_code: str) -> list[dict]:
    """Configured Chatterbox reference clips for a 2-letter language code."""
    return SETTINGS.get("reference_voices", {}).get(lang_code, [])
```

Also surface `SETTINGS["tts"]["engine"]` with a `DEFAULT_ENGINE` fallback. `settings.py`
imports nothing but stdlib — keep it that way.

---

## 6. Wizard UI — engine selector + reference clip field

Follow CLAUDE.md §390 *Adding a new UI control*.

In `wizard_steps.py`, the format card already builds a Voice row at **lines 454–461** and
reveals it via `_Reveal` at **555**, repopulating through `repopulate_voices()` at **590**.
Mirror that structure exactly:

1. **Engine combo** above the Voice row:
   `Engine: [ Chatterbox (voice cloning) | Kokoro (built-in voices) ]`,
   defaulting from `SETTINGS["tts"]["engine"]`. Connect `currentIndexChanged` to both
   `self.changed.emit()` and a new `_on_engine_changed()`.

2. **Reference clip row**, hidden unless Chatterbox is selected:
   - `QComboBox` populated from `reference_voices_for_language(lang)` using
     `addItem(label, userData=value)`, exactly like `repopulate_voices()`
   - a **Browse…** button opening `QFileDialog.getOpenFileName` filtered to
     `Audio (*.wav *.mp3 *.flac)` — **not** m4a/ogg/opus, which need ffmpeg, and **not**
     video containers; a WAV renamed to `.avi` fails with `DecodeError: unsupported file
     format`
   - a browsed path is added to the combo and selected, so it behaves like a picked entry

3. **Mutual exclusion:** Chatterbox → show reference row, hide Voice row. Kokoro → the
   reverse. Wrap both in `_Reveal` like the existing `_voice_reveal` so the animation is
   consistent.

4. Add `repopulate_reference_clips(target_is_spanish: bool)` alongside
   `repopulate_voices()`, and call it from the same place the language change is handled
   (see the comment at line 321, "Changing this re-populates the MP3 voice list in step 3").

Colours must come from `bookweaver.json` via `settings.py` (CLAUDE.md rule 2) — do not
hardcode hex.

---

## 7. Config plumbing

Per CLAUDE.md §390, thread the two new values through:

1. `_build_config()` (in `app.py`, and check `wizard_logic.py` for the wizard's own
   builder) → add `"tts_engine"` and `"reference_clip"`.
2. Resume block in `_on_resume()` → include both, so a resumed run keeps the engine.
3. `worker.py` → extract in `_generate_mp3` (below).

**`app.py` availability check.** It currently probes Kokoro cheaply via
`importlib.util.find_spec("kokoro")` to avoid importing torch at startup (CLAUDE.md rule
1). Add the equivalent for Chatterbox — `find_spec("mlx_audio")` — and gate the engine
options on what is actually installed. `app.py` must still never import `tts`.

---

## 8. `worker.py → _generate_mp3`

Currently at **`worker.py:488–548`**. Changes:

```python
from tts import (
    engine_available, kokoro_lang_code, chatterbox_lang_code, synthesise_book,
)

engine = cfg.get("tts_engine", SETTINGS.get("tts", {}).get("engine", "chatterbox"))
ok, err = engine_available(engine)
if not ok:
    self.log.emit(
        f"MP3 requested but {engine} is not installed ({err}). "
        f"See {'chatterbox.md' if engine == 'chatterbox' else 'kokoro.md'}.",
        "error",
    )
    return
```

Then branch on engine for the pre-flight validation:

- **chatterbox** — require `cfg["reference_clip"]`; emit a clear error naming
  `reference_voices` in `bookweaver.json` if missing, mirroring the existing
  "no voice is selected" message at line 512
- **kokoro** — keep the existing `voice` check unchanged

Pass the new arguments through to `synthesise_book`, reading the Chatterbox knobs from
`SETTINGS["tts"]`. Add an `on_sentence` callback that logs sparsely — **do not** emit a
line per sentence for a whole book; log every N sentences or only at chapter granularity,
or the console will be flooded.

Keep the existing contract: `_generate_mp3` **never raises** — a synthesis failure must
not undo already-written text output (`worker.py:495`).

Update the log line at 522 ("downloads the Kokoro model into .hf_cache/") to name the
selected engine and its real size (~2.7 GB for Chatterbox).

---

## 9. Fallback if §1 showed MLX is broken off the main thread

Only if the check in §1 failed. Do not build this speculatively.

Run synthesis in a **subprocess** rather than in `ProcessingWorker`:

- add `scripts/synthesise_chatterbox.py` taking a JSON job file (chapters, reference clip,
  language, params, output path) and writing the MP3 itself — it runs on *its own* main
  thread, so MLX behaves
- `_generate_mp3` launches it with `subprocess.Popen`, reads progress lines from stdout,
  and re-emits them through `self.log`
- cancellation becomes process termination, which is *better* than today: Chatterbox
  cannot be interrupted mid-call otherwise
- the subprocess pays the model load (~2.4s warm) once per book, which is negligible

This also isolates a 2.7 GB model from the GUI process.

---

## 10. Tests

`tests/conftest.py` already stubs Qt and the optional TTS packages. Add an `mlx_audio`
stub there the same way, so `tts.py` imports cleanly without MLX installed. Never stub
`numpy` (existing note in CLAUDE.md §366).

Add to `tests/test_tts.py` — all pure, no model:

- `split_sentences`: empty input, single sentence, multiple sentences, a >300-char
  sentence being split at clause boundaries, a single unbroken long word, and that the
  words round-trip in order
- `chatterbox_lang_code`: `"es"`/`"en"` pass through, `"ES"` normalises, an unsupported
  code raises
- `engine_available`: returns a 2-tuple for both engines and does not raise when a
  package is missing
- `synthesise_book` with `engine="chatterbox"` and no `reference_clip` raises a clear
  error **before** attempting to load a model (monkeypatch `_load_chatterbox` to assert it
  is never called)
- existing Kokoro tests must still pass untouched — that is the regression guard

Run `pytest -q`. One pre-existing failure in
`test_settings.py::TestOllamaTimeout::test_defaults_when_missing` is known and unrelated
(CLAUDE.md §384) — do not "fix" it as part of this work.

---

## 11. Documentation

1. **`docs/chatterbox.md`** — mirror `kokoro.md`: install
   (`pip install -r requirements-tts-chatterbox.txt`), the 2.7 GB model download, where it
   caches (`.hf_cache/`), and guidance on reference clips (10–20s, clean, single speaker,
   no music; accent of the clip decides the accent of the output; WAV/MP3/FLAC only).
   Note that the first ever run also pulls `S3TokenizerV2`.
2. **`CLAUDE.md`** — update the file map, add `mlx_audio` to the allowed `tts` imports in
   the import-flow rules (§53), and document the `engine` / `reference_voices` config keys
   in §92 and §127.
3. **`README.md`** — mention the engine choice and that Chatterbox is the default.

---

## 12. Definition of done

- [ ] §1 thread-affinity check run, result recorded, plan chosen accordingly
- [ ] `pytest -q` passes (except the known `test_settings` failure)
- [ ] Kokoro path still produces a chaptered MP3, byte-comparable to before the change
- [ ] Chatterbox path produces a chaptered MP3 from a 2–3 chapter book with a reference clip
- [ ] Chapter markers verified: `ffprobe`/`mutagen` shows CHAP/CTOC entries matching titles
- [ ] Switching engine in the wizard shows/hides the right field and survives resume
- [ ] Missing reference clip fails fast with a readable message, before the model loads
- [ ] A long chapter shows progress rather than appearing frozen

## Known limitations to state in the UI or docs, not to solve

- Sentence stitching can leave audible seams; `sentence_gap_ms` is the tuning knob.
- Chatterbox has one `"es"` — Castilian vs Latin American comes from the reference clip.
- The MLX port contains **no watermarking**, unlike upstream Chatterbox, so output carries
  no synthetic-audio provenance signal.
- Generation is ~2× real time: a 10-hour book is roughly 5 hours of compute.