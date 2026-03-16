# BookWeaver

**BookWeaver** is a desktop app that takes an English EPUB, compresses each
chapter to a chosen length, then rewrites it in Spanish at a target CEFR
language level — all powered by a local [Ollama](https://ollama.com) model.

---

## Features

| Feature | Detail |
|---|---|
| EPUB source | File picker filtered to `.epub` files |
| Model selection | Dropdown loaded from `bookweaver_settings.json` — no code changes to add models |
| CEFR levels | B1 · B2 · C1 · C2 |
| Summarisation slider | Keep 10–90 % of each chapter; sweet spot highlighted at 30–50 % |
| Creativity slider | 1–10 scale controlling LLM elaboration freedom and Ollama temperature |
| Output format | Plain text (`.txt`) or EPUB (`.epub`) |
| EPUB metadata | Title, Author, Language, Contributor — pre-filled from source file |
| Output folder | Configurable; defaults to the same folder as the source file |
| Proper noun rule | Character and place names are never translated |
| First-chapter mode | Process only chapter 1 for fast prompt testing |
| Abort | Cleanly stops after the current Ollama call |

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally (`http://localhost:11434`)
- At least one model pulled, e.g. `ollama pull gemma3:27b`

### Python dependencies

```bash
pip install PyQt6 ebooklib httpx beautifulsoup4
```

---

## Running

```bash
cd book_weaver
python main.py
```

---

## Project structure

```
book_weaver/
├── main.py                   Entry point — creates QApplication and main window
├── app.py                    BookWeaverApp (QMainWindow) — all UI wiring
├── worker.py                 ProcessingWorker (QThread) — pipeline logic
├── prompts.py                LLM prompt builders
├── widgets.py                Reusable custom Qt widgets
├── settings.py               Colours, stylesheet, settings loader
├── bookweaver_settings.json  Model list and default — edit freely
└── .pycodestyle              pycodestyle config (suppresses E221)
```

---

## Configuration

### Adding a model

Edit `bookweaver_settings.json`:

```json
{
  "models": [
    { "label": "My Custom Model", "value": "mymodel:tag" }
  ],
  "default_model": "mymodel:tag"
}
```

Restart the app and the new model appears in the dropdown.

### Tuning prompts

Open `prompts.py`. The two functions `build_summary_prompt` and
`build_rewrite_prompt` contain all instructions sent to the LLM.
The CEFR level guidance and creativity tier descriptions are plain
string constants — edit them directly.

---

## Recommended settings

| Setting | Value | Why |
|---|---|---|
| Summarisation | 30–50 % | Keeps core story, removes padding |
| Creativity | 5–6 | Adds atmosphere without inventing events |
| Model | `gemma3:27b` | Fast on Apple Silicon, good Spanish quality |
| First chapter only | ✅ on first run | Validate prompts cheaply before full run |

---

## Hardware notes

Tested on **MacBook M2 Max 96 GB**.  
`gemma3:27b` (Q4, ~18 GB) leaves ~75 GB free — no swapping.  
Expected throughput: ~25 tokens/second → ~30 s per rewritten chapter.  
A 30-chapter book takes roughly **1–2 hours** end-to-end.

`llama3.3:70b` (~43 GB) fits comfortably in 96 GB and produces higher
quality Spanish, but runs at ~10–12 tokens/second.
Switch by changing `default_model` in the settings file.
