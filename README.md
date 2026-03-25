# BookWeaver

**BookWeaver** is a desktop app that takes an English EPUB, condenses each
chapter to a chosen length, then rewrites it in Spanish at a target CEFR
language level — all powered by a local [Ollama](https://ollama.com) model.

---

## Features

| Feature | Detail |
|---|---|
| EPUB source | File picker filtered to `.epub` files |
| Model selection | Dropdown loaded from `bookweaver.json` — no code changes to add models |
| CEFR levels | B1 · B2 · C1 · C2 |
| Condensation slider | Keep 10–90 % of each chapter; sweet spot highlighted at 30–50 % |
| Creativity slider | 1–10 scale controlling LLM elaboration freedom and Ollama temperature |
| Chapter chunking | Chapters over 2000 words are split at paragraph boundaries, processed in chunks, then rejoined |
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
  "ollama_timeout": 600
}
```

The timeout can also be adjusted per-run in the UI without restarting.

### Tuning prompts

Open `prompts.py`. The two functions `build_summary_prompt` and
`build_rewrite_prompt` contain all instructions sent to the LLM.
The CEFR level guidance and creativity tier descriptions are plain
string constants — edit them directly.

---

## Chapter chunking

Chapters longer than 2000 words are automatically split at paragraph
boundaries. Each chunk is summarised and rewritten independently, then
the Spanish output is rejoined into a single chapter. The log shows
progress as `Chapter 3.1/4`, `3.2/4` etc. when chunking is active.

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

| Setting | Value | Why |
|---|---|---|
| Condensation | 30–50 % | Keeps core story, removes padding |
| Creativity | 5–6 | Adds atmosphere without inventing events |
| Model | `gemma3:27b` | Fast on Apple Silicon, good Spanish quality |
| Timeout | 600 s | Enough for large chapters; increase for slow hardware |
| First chapter only | ✅ on first run | Validate prompts cheaply before full run |

---

## Hardware notes

Tested on **MacBook M2 Max 96 GB**.  
`gemma3:27b` (Q4, ~18 GB) leaves ~75 GB free — no swapping.  
Expected throughput: ~25 tokens/second → ~30 s per rewritten chapter.  
A 30-chapter book takes roughly **1–2 hours** end-to-end.

`llama3.3:70b` (~43 GB) fits comfortably in 96 GB and produces higher
quality Spanish, but runs at ~10–12 tokens/second.
Switch by changing `default_model` in `bookweaver.json`.
