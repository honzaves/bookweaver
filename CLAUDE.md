# CLAUDE.md — BookWeaver context for AI assistants

This file gives a future Claude session enough context to make changes
to this codebase safely without breaking what already works.

---

## What this project does

BookWeaver is a PyQt6 desktop app.  
It reads an English EPUB, compresses each chapter via Ollama, then
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
| `settings.py` | Colours, stylesheet, settings loader | For theme/style changes |
| `bookweaver_settings.json` | Model list | User edits; no code changes |

---

## Architecture rules

1. **Imports flow one way:**  
   `main` → `app` → `worker`, `widgets`, `settings`  
   `worker` → `prompts`, `settings`  
   `widgets` → `settings`  
   `prompts` → nothing  
   `settings` → nothing (stdlib only)  
   Never import `app` or `worker` from `widgets` or `settings`.

2. **All colours come from `settings.py`.**  
   Never hardcode hex values in `app.py` or `widgets.py`.

3. **SETTINGS is a module-level singleton in `settings.py`.**  
   Import it as `from settings import SETTINGS`.

4. **ProcessingWorker must never import Qt UI classes** — it runs in a
   background thread and communicates only via pyqtSignal.

5. **`prompts.py` has no Qt dependency at all.**  
   Keep it that way — it makes prompt testing trivial without a GUI.

---

## Known historical issues

Repeated `str_replace` edits have previously caused `class Foo(Bar):`
declaration lines to be silently dropped, leaving orphaned methods that
crash at runtime with confusing `TypeError` messages.

**After any edit that touches a class boundary, verify with:**

```bash
grep -n "^class " *.py
```

Expected output (one line per class, in order):

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

## Adding a new UI control

1. Add the widget to `widgets.py` if it's reusable, or inline in `app.py`
   if it's specific to one group.
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

All LLM instructions live in `prompts.py`.  
- `_LEVEL_GUIDANCE` — per-CEFR-level Spanish writing instructions  
- `_creativity_instruction()` — maps creativity 1–10 to prose directives  
- `build_summary_prompt()` — compression prompt  
- `build_rewrite_prompt()` — Spanish rewrite prompt  

Changes here affect output quality immediately with no UI changes.

---

## PEP 8 notes

- `E221` (aligned assignments) is suppressed in `.pycodestyle` — this is
  intentional for readability in colour/config blocks.
- Max line length is 100.
- Run `pycodestyle --statistics *.py` to check.
