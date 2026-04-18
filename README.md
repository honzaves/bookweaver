# BookWeaver

**BookWeaver** is a desktop app that takes an English EPUB and produces a
Spanish version of it — all powered by a local [Ollama](https://ollama.com) model.

Two processing modes are available:

- **Summarise → Rewrite** — condenses each chapter to a chosen length, then
  rewrites it in Spanish at a target CEFR level. Good for creating a shorter,
  reader-friendly Spanish adaptation.
- **Full translation** — translates the complete text directly, preserving
  every sentence and paragraph. Good when you want an accurate Spanish
  rendition rather than a condensed retelling.

Both modes use the same creativity and CEFR-level controls, and both support
chapter chunking, resume-after-failure, and all output formats.

---

## Features

| Feature | Detail |
|---|---|
| EPUB source | File picker filtered to `.epub` files |
| Model selection | Dropdown loaded from `bookweaver.json` — no code changes to add models |
| CEFR levels | B1 · B2 · C1 · C2 |
| Processing mode | **Summarise → Rewrite** (condense then rewrite) or **Full translation** (direct, no cuts) |
| Condensation slider | Keep 10–90 % of each chapter; visible only in Summarise → Rewrite mode |
| Creativity slider | 1–10 scale controlling LLM elaboration freedom and Ollama temperature |
| Chapter chunking | Long chapters are split at paragraph boundaries into configurable-size chunks, processed independently, then rejoined |
| Chunk size | Configurable in the UI (200–10 000 words; default 2 000) |
| Output format | Plain text (`.txt`) or EPUB (`.epub`) |
| EPUB metadata | Title, Author, Language, Contributor — pre-filled from source file |
| Output folder | Configurable; defaults to the same folder as the source file |
| Proper noun rule | Character and place names are never translated |
| First-chapter mode | Process only chapter 1 for fast prompt testing |
| Timeout | Configurable per-run in the UI; default set in `bookweaver.json` |
| Resume | After a timeout or failure, resume from the failed chapter with one click |
| Abort | Cleanly stops after the current Ollama call |

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally (`http://localhost:11434`)
- At least one model pulled, e.g. `ollama pull gemma3:27b`

### Python dependencies

```bash
pip install -r requirements.txt
```

Or for development (includes pytest):

```bash
pip install -r requirements-dev.txt
```

---

## Running

```bash
python main.py
```

---

## Project structure

```
bookweaver/
├── main.py              Entry point — creates QApplication and main window
├── app.py               BookWeaverApp (QMainWindow) — all UI wiring
├── worker.py            ProcessingWorker (QThread) — pipeline logic
├── prompts.py           LLM prompt builders
├── widgets.py           Reusable custom Qt widgets
├── settings.py          Config loader — reads bookweaver.json, builds stylesheet
├── bookweaver.json      All user-editable settings: colours, models, timeout
├── pyproject.toml       Project metadata and tool config
├── requirements.txt     Runtime dependencies
├── requirements-dev.txt Dev/test dependencies
└── tests/
    ├── conftest.py      PyQt6 stubs so tests run without Qt installed
    ├── test_prompts.py
    ├── test_settings.py
    └── test_worker.py
```

---

## Configuration

Everything user-editable lives in `bookweaver.json`. No Python changes needed.

### Adding a model

```json
{
  "models": [
    { "label": "My Custom Model", "value": "mymodel:tag" }
  ],
  "default_model": "mymodel:tag"
}
```

### Changing colours

Edit the `"colors"` block. All values are standard `#RRGGBB` hex.

### Changing the default timeout

```json
{
  "ollama_timeout": 1200
}
```

The timeout can also be adjusted per-run in the UI without restarting.

### Tuning prompts

Open `prompts.py`. Three prompt-builder functions contain all instructions
sent to the LLM:

| Function | Used by |
|---|---|
| `build_summary_prompt` | Summarise → Rewrite mode, step 1 |
| `build_rewrite_prompt` | Summarise → Rewrite mode, step 2 |
| `build_translation_prompt` | Full translation mode |

The CEFR level guidance and creativity tier descriptions are plain string
constants — edit them directly and both modes will pick up the changes.

---

## Processing modes in detail

### Summarise → Rewrite

Each chapter goes through two LLM calls per chunk:

1. **Summarise** — condenses the chunk to the target word count set by the
   condensation slider (10–90 % of the original).
2. **Rewrite** — rewrites the condensed English as a Spanish narrative chapter
   at the chosen CEFR level and creativity setting.

Good for: producing a shorter, more readable Spanish adaptation; language
learners who want a simpler retelling.

### Full translation

Each chapter chunk goes through a single LLM call:

1. **Translate** — the complete chunk text is translated into Spanish at the
   chosen CEFR level. Nothing is removed or condensed.

Good for: faithful Spanish versions; readers who want the full story.

> **Note:** full translation produces significantly longer output and therefore
> takes more time and tokens per chapter than the summarise pipeline.

---

## Chapter chunking

Chapters longer than the configured chunk size are automatically split at
paragraph boundaries. Each chunk is processed independently (summarised +
rewritten, or translated), then the Spanish output is rejoined into a single
chapter. The log shows progress as `Chapter 3.1/4`, `3.2/4` etc. when chunking
is active.

The chunk size defaults to **2 000 words** and can be adjusted in the Options
panel (200–10 000 words). Smaller chunks reduce per-call token usage and
timeout risk; larger chunks give the LLM more context and can produce more
coherent output for dense chapters.

---

## Resume after failure

If a run fails mid-book (timeout, Ollama error, etc.), a **Resume** button
appears in the UI. Any chapters already completed are preserved. Adjust the
timeout spinbox if needed, then press Resume to continue from where it
stopped — no work is repeated.

---

## Running tests

```bash
pytest
```

No Qt installation required — the test suite stubs out PyQt6.

---

## Recommended settings

### Summarise → Rewrite mode

| Setting | Value | Why |
|---|---|---|
| Condensation | 30–50 % | Keeps core story, removes padding |
| Creativity | 5–6 | Adds atmosphere without inventing events |
| Chunk size | 2 000 words | Safe default for most models |
| Model | `gemma3:27b` | Fast on Apple Silicon, good Spanish quality |
| Timeout | 900 s | Enough for large chapters at moderate keep % |
| First chapter only | ✅ on first run | Validate prompts cheaply before full run |

### Full translation mode

| Setting | Value | Why |
|---|---|---|
| Creativity | 3–5 | Stay close to source; lower creativity = more literal |
| Chunk size | 1 000–1 500 words | Smaller chunks reduce timeout risk on long chapters |
| Timeout | 1 200 s | Translation generates more tokens than a condensed rewrite |

---

## Hardware notes

Tested on **MacBook M2 Max 96 GB**.
`gemma3:27b` (Q4, ~18 GB) leaves ~75 GB free — no swapping.
Expected throughput: ~25 tokens/second → ~30 s per rewritten chapter
(summarise → rewrite mode); longer in full translation mode.
A 30-chapter book takes roughly **1–2 hours** end-to-end in summarise mode,
and **2–4 hours** in full translation mode, depending on chapter length.

`llama3.3:70b` (~43 GB) fits comfortably in 96 GB and produces higher
quality Spanish, but runs at ~10–12 tokens/second.
Switch by changing `default_model` in `bookweaver.json`.
