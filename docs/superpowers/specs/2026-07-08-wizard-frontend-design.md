# BookWeaver Guided Wizard — Frontend Design Spec

**Date:** 2026-07-08
**Status:** Approved (design phase)
**Source material:** `docs/design_handoff_bookweaver_wizard/{README.md, ui-design-brief.md, screenshots/}`

---

## 1. Goal

Recreate the "Guided Wizard" design — a 4-step stepper (Book → Transform →
Output → Run) with a pinned run drawer — as a **second, standalone PyQt6
frontend** that coexists with the current `app.py` UI.

**Non-goal:** changing pipeline behavior. The wizard is a new view onto the
existing `ProcessingWorker`.

---

## 2. Constraints (decided, not open)

| Constraint | Decision |
|---|---|
| Stack | PyQt6, same as the current app |
| Coexistence | New entry point `wizard.py`. `main.py` and `app.py` untouched. |
| End state | The wizard replaces `app.py` once proven. Duplicating UI logic now is acceptable; no shared-abstraction extraction. |
| Backend | mlx is default. UI copy is backend-aware, never hardcodes "Ollama". |
| Branch | `main`. Every commit leaves `python main.py` runnable. |
| Palette | Additive `wizard_colors` block in `bookweaver.json`. The existing `colors` block is not modified. |
| Window | Default 860×724, min 760×640, resizable, content area scrolls. |
| Tests | Pure logic only (`wizard_logic.py`). Qt painting untested, as today. |

### Files touched outside the new module set

**`worker.py` — three lines.** Backward-compatible: `app.py` never sets
`max_tokens`, so it keeps the `bookweaver.json` default.

```python
# __init__, after self._backend
self._max_tokens = config.get("max_tokens", SETTINGS.get("mlx_max_tokens", 8192))

# _run(), line ~122   (was: SETTINGS.get('mlx_max_tokens', 8192))
f"at {self._max_tokens} tokens.",

# _llm_call(), line ~916   (was: SETTINGS.get("mlx_max_tokens", 8192))
max_tokens=self._max_tokens,
```

Both `SETTINGS` reads must change. Fixing only `_llm_call` leaves the
`ℹ️ mlx backend: … output capped at N tokens.` log line reporting the JSON
default while the worker actually uses the spinbox value.

**`bookweaver.json` — one additive block.** `wizard_colors` (§6).

**`assets/` — new directory.** `Caveat-Regular.ttf` + `OFL.txt`.

Nothing else. `app.py` and `widgets.py` are imported by no new file.

---

## 3. Module decomposition

```
wizard.py            Entry point + WizardWindow shell:
                     header, amber rule, step rail, recap line,
                     QStackedWidget content area, pinned footer.
                     Owns WizardState and the ProcessingWorker.

wizard_theme.py      Reads bookweaver.json["wizard_colors"] → W_* constants.
                     Builds WIZARD_STYLESHEET. Loads Caveat via
                     QFontDatabase with a graceful fallback.

wizard_logic.py      PURE, Qt-free, fully unit-tested. The only load-bearing
                     module — the single seam where a cosmetic rewrite can
                     silently break the pipeline.

wizard_widgets.py    Custom-painted reusable widgets: WizardSlider,
                     ModeTileGrid, StepRail, TriStateChapterList,
                     RunConsole, Field/Stepper/Checkbox primitives.

wizard_steps.py      StepBook, StepTransform, StepOutput, StepRun —
                     one QWidget subclass each.
```

### Import flow (extends CLAUDE.md rule #1; no cycles)

```
wizard → wizard_steps → wizard_widgets → wizard_theme
wizard → wizard_logic   (Qt-free; imports settings only for
                         creativity_to_temperature and TARGET_LANG)
wizard → worker         (lazy, inside _on_start)
wizard → epub_io        (lazy, inside _on_epub_selected)

wizard_theme  → stdlib + PyQt6.QtGui only (never settings, never app)
wizard_logic  → settings only (never Qt, never app/worker/widgets, never theme)
wizard_widgets→ wizard_theme + wizard_logic (never settings)
```

`wizard_theme.py` loads `bookweaver.json` itself with `json.load`. It does not
import `settings.py` — that module's `_build()` runs at import time and
populates the *old* UI's globals. The duplicated loader is deliberate: it keeps
the two themes from sharing mutable state.

**`wizard_logic.py` never returns a hex color.** It returns semantic ramp keys
(`"muted" | "neutral" | "green" | "warning" | "error"`); `wizard_widgets.py`
maps those to `W_*` constants from `wizard_theme`. This is what keeps
`wizard_logic` free of both Qt and the palette, and therefore unit-testable
under the existing `conftest.py` stub.

`wizard.py` must not import `tts` (checks Kokoro via
`importlib.util.find_spec("kokoro")`, avoiding a torch load at startup) and
must not import `llm` (checks mlx via `find_spec("mlx_lm")`) — the same rules
`app.py` follows.

---

## 4. The data contract

`wizard_logic.build_config(state) -> dict` must emit **exactly** the keys
`ProcessingWorker._run()` reads. Verified against `worker.py:98-118, 146, 169,
472, 502, 510` and `worker.py:916`.

| Key | Source | Notes |
|---|---|---|
| `epub_path` | Step 1 file picker | |
| `model` | Step 1 combo `.currentData()` | value, not label |
| `backend` | `SETTINGS["llm_backend"]` | captured at build time so resume never flips backend |
| `selected_chapters` | Step 1 tri-state list | `list[int]` |
| `mode` | Step 2 tiles | **mapped**, see below |
| `level` | Step 2 combo | `B1`–`C2` |
| `keep_pct` | Step 2 slider | 10–90 |
| `creativity` | Step 2 slider | 1–10 |
| `carry_mode` | Step 2 combo | **mapped**, see below |
| `summary_lang` | Step 2 key-ideas toggle | `"en"` if English tile else `"es"` |
| `target_lang` | derived | `summary_lang` if mode is key-ideas, else `TARGET_LANG[mode]` |
| `out_format` | Step 3 checkboxes | `list[str]`, order `txt, epub, html` |
| `out_folder` | Step 3 picker | falls back to `Path(epub_path).parent` |
| `generate_mp3` | Step 3 checkbox | |
| `voice` | Step 3 combo | `None` when mp3 unchecked |
| `meta_title` | Step 3 | **flat key, not nested** |
| `meta_creator` | Step 3 | flat |
| `meta_language` | Step 3 | flat, `or "es"` |
| `meta_contributor` | Step 3 | flat |
| `chunk_size` | Step 3 stepper | 200–10000, step 100 |
| `timeout` | Step 3 stepper *or* state default | 30–3600, step 30 |
| `max_tokens` | Step 3 stepper *or* state default | **new key** |

`build_config` **always emits all 21 keys**, on both backends. Only one of
`timeout` / `max_tokens` is surfaced as a Step-3 control at a time (§7); the
other carries its `WizardState` default. This keeps the dict shape constant, so
the resume spread and the key-set regression test (§8) do not have to branch on
backend. The worker ignores whichever key its backend does not use —
`self._timeout` is unread on mlx, `self._max_tokens` is unread on ollama.

There is no `epub_meta` sub-dict. The worker reads four flat `meta_*` keys and
assembles its own `meta` dict at `worker.py:113-118`.

### Enum mappings

The design's state names differ from the worker's. `build_config` translates:

```python
MODE_TO_WORKER = {
    "sr":   "summarise_rewrite",
    "full": "translate",
    "sum":  "summarise_only",
    "key":  "summarise_key_ideas",
}
CARRY_TO_WORKER = {
    "off":   "off",
    "names": "glossary",
    "tail":  "prose",
    "both":  "both",
}
```

### Derived quantities

```python
def derive_target_is_spanish(mode: str, key_ideas_lang: str) -> bool:
    return mode in ("sr", "full") or (mode == "key" and key_ideas_lang == "es")
```

Gates three things: the Step-2 Spanish-level card, the level segment of the
recap line, and which voice list Step 3 populates.

### Resume round-trip

Mirrors `app.py:_on_resume`, **plus** `max_tokens`:

```python
cfg = {
    **self._resume_state["config"],
    "timeout":       self._timeout_spin.value(),   # ollama
    "max_tokens":    self._tokens_spin.value(),    # mlx
    "chunk_size":    self._chunk_spin.value(),
    "resume_from":   self._resume_state["from_chapter"],
    "prior_results": self._resume_state["results"],
}
```

`max_tokens` is in the override set because the wizard's failure copy on mlx
reads "Adjust settings, then press Resume." Without the override, adjusting the
spinbox would not reach the worker and the copy would be false. The old
`app.py` does not override it, and does not need to — it has no such control.

Because `selected_chapters` rides along via `**config`, a resumed run
reprocesses the same subset and `resume_from` indexes into that filtered list.

---

## 5. State, validation, lifecycle

### WizardState

A plain dataclass in `wizard_logic.py`. Step widgets read from it and write
through setters that emit one `stateChanged` signal; the shell recomputes
derived UI (recap line, badge flags, Start enablement) on every change.

```python
@dataclass(frozen=True)
class ChapterRow:
    index: int          # index into epub_io.extract_chapters() output
    title: str
    checked: bool = True


def _default_formats() -> dict[str, bool]:
    return {"txt": True, "epub": False, "html": False}


@dataclass
class WizardState:
    step: int = 1
    epub_path: str = ""
    book_title: str = ""
    book_author: str = ""
    chapters: list[ChapterRow] = field(default_factory=list)
    model: str = ""                 # seeded from SETTINGS["default_model"]
    mode: str = "sr"                # sr | full | sum | key
    key_ideas_lang: str = "es"      # es | en
    cefr_level: str = "B2"          # B1 | B2 | C1 | C2
    carry: str = "off"              # off | names | tail | both
    keep_pct: int = 40
    creativity: int = 5
    formats: dict[str, bool] = field(default_factory=_default_formats)
    mp3_enabled: bool = False
    voice: str | None = None
    out_folder: str = ""
    meta_title: str = ""
    meta_creator: str = ""
    meta_language: str = "es"
    meta_contributor: str = ""
    timeout_sec: int = 1200         # seeded from settings.OLLAMA_TIMEOUT
    max_tokens: int = 8192          # seeded from SETTINGS["mlx_max_tokens"]
    chunk_words: int = 2000
    run_state: str = "idle"         # idle|running|success|failed|aborting|aborted
```

`mp3_available` is **not** state — it is
`importlib.util.find_spec("kokoro") is not None`, computed once at startup.

### Validation

One source of truth, three consumers:

```python
def validation_errors(state) -> list[tuple[int, str]]:
    errs = []
    if not state.epub_path:
        errs.append((1, "Select an EPUB file"))
    if not any(r.checked for r in state.chapters):
        errs.append((1, "Select at least one chapter"))
    if not any(state.formats.values()):
        errs.append((3, "Select at least one output format"))
    return errs
```

1. Start: `setEnabled(not errs)`; tooltip `" · ".join(msg for _, msg in errs)`
2. Step badges in `{step for step, _ in errs}` render with the error border
3. Decorations clear the instant the predicate is satisfied

**Resolved conflict:** `ui-design-brief.md` §7.3 says validation failure writes
a warning line to the log with no modal; `README.md` says gate visibly before
Start by disabling it and flagging the step. We do both — but because Start is
disabled, the log-warning path is unreachable. It was the fallback for a UI
that could not gate. `app.py:558-577` keeps its log-warning behavior, untouched.

### Run lifecycle

| Transition | Trigger | UI effect |
|---|---|---|
| `idle → running` | Start | jump to step 4; Start → `● Running…` disabled; Abort enabled; Resume hidden; steps 1–3 remain navigable but read-only |
| `running → success` | `finished(True, path)` | progress 100%; green `🎉 All done! Output: <path>`; Start → `▶ Start over` |
| `running → failed` | `finished(False, path)` | red `✗` line; if `worker.completed_results` non-empty → amber `💾 N chapter(s) saved. {resume_hint(backend)}` + Resume button |
| `running → aborting` | Abort | Abort disabled, relabeled `Stopping…`; muted log line `Abort requested — will stop after the current chunk.` |
| `aborting → aborted` | `finished(False, …)` | same as failed. **Aborted runs are resumable** — `completed_results` is populated identically. |

```python
def resume_hint(backend: str) -> str:
    return ("Raise the timeout, then press Resume." if backend == "ollama"
            else "Adjust settings, then press Resume.")
```

`ProcessingWorker._abort` is polled at **chunk** boundaries
(`worker.py:187, 219, 289, 335`), never mid-generation. On mlx an in-flight
call cannot be interrupted, so Abort lands after the current chunk's LLM call
returns — seconds to minutes. The `Stopping…` pending state makes that latency
honest. No worker change.

---

## 6. Theme

### `wizard_colors` (additive block in `bookweaver.json`)

```json
"wizard_colors": {
  "app_bg":        "#0a0a08",
  "window_bg":     "#111210",
  "surface":       "#1a1b18",
  "inset":         "#0f0f0c",
  "console_bg":    "#0c0c09",
  "footer_bg":     "#16160f",
  "border":        "#2e2f2a",
  "border_input":  "#36372f",
  "border_strong": "#3a3b34",
  "border_ctrl":   "#4a4b42",
  "amber":         "#d4a853",
  "amber_hover":   "#deb469",
  "amber_dim":     "#8a6a2e",
  "text":          "#e8e4d9",
  "text_secondary":"#cfc9ba",
  "muted":         "#7a7870",
  "muted2":        "#8a8678",
  "faint":         "#6c6a62",
  "faint2":        "#55564d",
  "success":       "#7aab6e",
  "warning":       "#c98d3a",
  "error":         "#c0604a",
  "tile_selected": "#211c12"
}
```

Missing block → `SystemExit` with a clear message, matching
`settings._load_config`'s existing failure style. No silent fallback to a
broken palette.

### Log severities

`worker.log` is `pyqtSignal(str, str)` emitting exactly
`info | success | warning | error | muted`. The design also lists a `head`
severity — nothing emits it. Dropped. Unknown level falls back to `info`.

```
info    #9a978c      success #7aab6e      error #c0604a
muted   #5b594f      warning #c98d3a
```

Note these differ from `widgets.LogWidget.COLOURS`, which maps `info → C_TEXT`.
The wizard's console uses the design's dimmer `info`. No shared code.

### Typography

- UI: `-apple-system, "Helvetica Neue", Helvetica, system-ui, sans-serif`
- Mono: `ui-monospace, Menlo, monospace` — paths, field values, readouts, log
- Decorative: **Caveat** 16px, per-step hand-lettered prompts

Caveat is fetched from the `github.com/google/fonts` OFL mirror and committed
to `assets/` with its `OFL.txt`. It is not installed on this machine and is not
currently in the repo.

**Implementation risk:** Google ships `Caveat[wght].ttf` as a **variable**
font. Pulling a fixed weight through `QFontDatabase.addApplicationFont` is
fiddly in Qt. If it misbehaves, use the static instance from the `static/`
subdirectory of the same repo.

**Fallback:** `addApplicationFont` returns `-1` when the file is absent or
unparseable → render the prompts in muted italic system font. A fresh clone
without the asset must never crash.

---

## 7. Screens

Layout, spacing, radii, and colors follow `README.md` §"Design tokens" and
§"Screens / Views" exactly. Deviations, all previously agreed:

| Design says | We do | Why |
|---|---|---|
| Fake 38px title bar with traffic-light dots | Dropped; native macOS chrome | The dots exist to make an HTML mockup look like a desktop window. A real Qt window already has real ones. |
| Step 4 segmented control (Idle·Running·Success·Failed) | Dropped | `README.md` itself: "a prototype affordance for reviewing states — in production the state is driven by the actual job." |
| Subtitle "EPUB → Spanish rewriter via Ollama" | "…via local LLM" | Matches `app.py:143`. mlx is the default backend. |
| Model card titled "OLLAMA MODEL" | `MODEL (MLX)` / `MODEL (OLLAMA)` | Dynamic from `SETTINGS["llm_backend"]`, matching `app.py:178`. |
| Step 3 "Timeout per call" card | Backend-aware slot: **Max tokens per call** on mlx, **Timeout per call** on ollama | On mlx the timeout is inert (`app.py:382` disables it) and `mlx_max_tokens` is the real bound. |
| Failure copy "Raise the timeout, then press Resume" | `resume_hint(backend)` | On mlx there is no timeout to raise. |
| Creativity readout `temp ≈ 0.44` at level 5 | `temp ≈ 0.68` | The design used `(N-1)/9`. `settings.creativity_to_temperature()` — the value actually sent to the model — is `0.1 + (N-1)·(1.3/9)`. Code wins; the wizard calls the real function and duplicates no formula. |
| Recap `… · 11 chapters · Gemma 4 31B · B2` | `… · 3 / 11 chapters · Gemma 4 31B QAT · B2` | Reflects the actual selection. Model label truncated at the first `(`. Level segment omitted when `target_is_spanish` is false. |
| Creativity ramp: 9 = warning-amber (`widgets.py:140`) | 9–10 = error-red | Design's ramp: 1–2 muted, 3–4 neutral, 5–6 green, 7–8 warning `#c98d3a`, 9–10 error `#c0604a`. Lives in `wizard_widgets.py`; `widgets.py` keeps its ramp. |

### Conditional reveals

Animated via `QPropertyAnimation` on `maximumHeight` + `QGraphicsOpacityEffect`,
180ms, `OutCubic`. The brief's design goal #2 is explicitly "make the adaptive
logic legible… controls don't appear/vanish jarringly."

- Summarisation-depth card: hidden iff `mode == "full"`; creativity card then
  spans the row
- Translate note: `mode == "full"` only
- Summarise-only note: `mode == "sum"` only
- Key-ideas language card: `mode == "key"` only; toggling it re-populates the
  Step-3 voice list, preserving the selection when the voice exists in both
- Spanish level card: shown iff `derive_target_is_spanish(...)`
- Cross-chunk continuity card: **always visible**, all modes
- EPUB metadata card: shown iff `formats["epub"]`
- Voice dropdown: shown iff MP3 is available, `.txt` is selected, and checked

### Sliders (the signature interaction)

Custom-painted: 6px track (`#2a2b24`, radius 99px) with tick marks, 17px amber
knob with a 2px `#15150f` ring and soft shadow, gradient fill from `#5b594f` to
the current ramp color. An invisible native `QSlider` overlays the paint area
to handle interaction and keyboard focus.

- **Keep %** — 10–90, default 40, snap 10. Readout
  `Keep 40% of original (↓ 60% reduction)`. Sweet spot 30–50 → readout, knob,
  and fill turn green and a `✦ sweet spot` pill appears.
- **Creativity** — 1–10, default 5, snap 1. Readout
  `Enriched+ — level 5/10 (temp ≈ 0.68)`. Sweet spot 5–6 → green + pill.

---

## 8. Testing

`tests/test_wizard_logic.py` — pure functions only, runnable under the existing
`conftest.py` PyQt6 stub because `wizard_logic.py` imports no Qt.

| Function | Cases |
|---|---|
| `derive_target_is_spanish` | all 4 modes × both key-ideas languages (8) |
| `validation_errors` | empty state; no file; no chapter ticked; no format; all-valid; combinations |
| `build_config` | every one of the 21 keys present; mode + carry enum mappings; `target_lang` for key-ideas vs other modes; `voice is None` when mp3 off; `out_folder` fallback to `Path(epub_path).parent`; `meta_language` defaulting to `"es"` |
| `resume_hint` | `"mlx"` vs `"ollama"` |
| `creativity_notch` | all 10 notches → `(name, ramp_key)`; asserts 7–8 are `"warning"` and 9–10 are `"error"` (the design ramp, not `widgets.py`'s) |
| `keep_pct_readout` | boundaries 10, 29, 30, 50, 51, 90 → `(text, is_sweet)` |
| `recap_text` | partial selection; all selected; label truncation at `(`; level omitted when English output |

A regression test asserting `set(build_config(state)) == EXPECTED_21_KEYS`
guards the contract against silent drift.

Qt painting, signal wiring, and reveal animations are not unit-tested —
consistent with `app.py` and `widgets.py` today.

`worker.py`'s `max_tokens` change gets one test: a config **without**
`max_tokens` falls back to `SETTINGS["mlx_max_tokens"]` (proving `app.py` is
unaffected), and a config **with** it uses the supplied value.

---

## 9. Verification

Every commit must leave both frontends runnable:

```bash
python main.py      # current UI, unchanged
python wizard.py    # new wizard UI
pytest -q           # incl. tests/test_wizard_logic.py
pycodestyle --config=.pycodestyle --statistics *.py
grep -n "^class " *.py     # class-boundary guard, per CLAUDE.md
```

Expected new entries in the `grep -n "^class "` output:

```
wizard.py:         class WizardWindow(QMainWindow)
wizard_steps.py:   class StepBook(QWidget)
wizard_steps.py:   class StepTransform(QWidget)
wizard_steps.py:   class StepOutput(QWidget)
wizard_steps.py:   class StepRun(QWidget)
wizard_widgets.py: class WizardSlider(QWidget)
wizard_widgets.py: class ModeTileGrid(QWidget)
wizard_widgets.py: class StepRail(QWidget)
wizard_widgets.py: class TriStateChapterList(QWidget)
wizard_widgets.py: class RunConsole(QWidget)
```

`CLAUDE.md`'s "Known historical issues" section pins the expected
`grep -n "^class "` output. It must be updated with these entries in the same
commit that introduces them, or the guard produces a false positive on every
subsequent run.

**Known pre-existing failure** (unrelated, do not fix here):
`test_settings.py::TestOllamaTimeout::test_defaults_when_missing` asserts a
default of `600`; `settings.py` has always defaulted to `1200`.

End-to-end acceptance: load an EPUB, deselect some chapters, run each of the
four modes to completion on a short book, and exercise the failure → Resume
path by setting `max_tokens` absurdly low.
