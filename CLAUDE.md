# CLAUDE.md — BookWeaver context for AI assistants

---

## What this project does

BookWeaver is a PyQt6 desktop app.  
It reads an English EPUB, condenses each chapter via Ollama, then
rewrites it in Spanish at a chosen CEFR level.

---

## File map

| File | Purpose | What to touch |
|---|---|---|
| `main.py` | Entry point only | Rarely |
| `app.py` | Main window, UI wiring, slot logic | For new UI elements |
| `worker.py` | Background thread, pipeline, file output | For pipeline changes |
| `prompts.py` | All LLM prompt strings | For prompt tuning |
| `widgets.py` | All reusable Qt widgets | For new/changed widgets |
| `settings.py` | Config loader — reads JSON, builds stylesheet | For loader logic changes |
| `bookweaver.json` | All user-editable settings: colours + models | User edits; no code changes |

---

## Architecture rules

1. **Imports flow one way:**  
   `main` → `app` → `worker`, `widgets`, `settings`  
   `worker` → `prompts`, `settings`  
   `widgets` → `settings`  
   `prompts` → nothing  
   `settings` → nothing (stdlib only)  
   Never import `app` or `worker` from `widgets` or `settings`.

2. **All colours come from `bookweaver.json` via `settings.py`.**  
   Never hardcode hex values anywhere else.

3. **`SETTINGS` is a module-level dict in `settings.py`**, populated by `_build()`
   at import time. Import it as `from settings import SETTINGS`.

4. **`ProcessingWorker` must never import Qt UI classes** — it runs in a
   background thread and communicates only via pyqtSignal.

5. **`prompts.py` has no Qt dependency at all.**

6. **`creativity_to_temperature()` lives in `settings.py`** — the single source
   of truth for the creativity→temperature mapping, used by both `worker.py`
   and `widgets.py`.

---

## Configuration system

All user-editable values live in `bookweaver.json`:

- `colors` — hex values for the full colour palette
- `models` — list of `{label, value}` objects for the model dropdown
- `default_model` — value string of the default selection

`settings.py` loads this file at import time via `_build()`, which:
1. Calls `_load_config()` — raises `SystemExit` on missing or malformed JSON
2. Populates all `C_*` colour constants as module globals
3. Builds `STYLESHEET` as an f-string from those constants
4. Populates the `SETTINGS` dict

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
widgets.py: class SummarizationSlider(QWidget)
widgets.py: class CreativitySlider(QWidget)
widgets.py: class FilePickerRow(QWidget)
widgets.py: class FolderPickerRow(QWidget)
widgets.py: class LogWidget(QTextEdit)
widgets.py: class ProgressBar(QWidget)
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
file I/O only — the Qt pipeline is integration territory).

---

## Adding a new UI control

1. Add the widget to `widgets.py` if reusable, or inline in `app.py`.
2. Add the field to `_build_config()` in `app.py`.
3. Extract the value in `worker.py`'s `run()` method.
4. Pass it to the appropriate prompt builder in `prompts.py` if relevant.

---

## Adding a new output format

1. Add the radio button in `app.py → _add_options_group()`.
2. Add a `_write_xxx()` method in `worker.py`.
3. Add the branch in `worker.py → run()` after `# ── write output ──`.

---

## Prompt tuning

All LLM instructions live in `prompts.py`:

- `_LEVEL_GUIDANCE` — per-CEFR-level Spanish writing instructions
- `_creativity_instruction()` — maps creativity 1–10 to prose directives
- `build_summary_prompt()` — condensation prompt (length-target driven, not "summarise")
- `build_rewrite_prompt()` — Spanish rewrite prompt

**Important:** `build_summary_prompt` frames the task as "condense to N words"
rather than "summarise" — LLMs treat "summarise" as a signal to produce short
output regardless of any percentage instruction. The prompt calculates a
concrete word-count target from the input length.

---

## PEP 8 notes

- `E221` (aligned assignments) is suppressed — intentional for colour/config blocks.
- Max line length is 100.
- Run `pycodestyle --statistics *.py` to check.
