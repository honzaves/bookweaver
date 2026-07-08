# BookWeaver Guided Wizard Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone PyQt6 "Guided Wizard" frontend (`wizard.py`) that drives the existing `ProcessingWorker`, coexisting with the untouched `app.py` UI.

**Architecture:** Five new modules. `wizard_logic.py` is pure Python (no Qt, no palette) and holds the entire data contract to the worker — it is the only load-bearing module and is fully unit-tested. `wizard_theme.py` owns colors and fonts. `wizard_widgets.py` holds custom-painted reusable widgets. `wizard_steps.py` holds one QWidget per wizard step. `wizard.py` is the shell + worker wiring. The only edit to existing Python is a 3-line `max_tokens` plumb in `worker.py`.

**Tech Stack:** Python 3.14, PyQt6, pytest. Existing modules reused as-is: `worker.py`, `epub_io.py`, `settings.py` (for `creativity_to_temperature` + `TARGET_LANG` only).

**Spec:** `docs/superpowers/specs/2026-07-08-wizard-frontend-design.md`

## Global Constraints

- **Never modify** `app.py`, `widgets.py`, `main.py`. They must keep working unchanged.
- **Never hardcode a hex color** outside `bookweaver.json`. (CLAUDE.md rule #2.)
- Branch: `main`. Every commit must leave both `python main.py` and `python wizard.py` runnable.
- Max line length **100**. Lint with `pycodestyle --config=.pycodestyle --statistics *.py` (pycodestyle 2.14 does not auto-read the file — pass `--config` explicitly).
- `wizard_logic.py` imports **only** stdlib + `settings` (`creativity_to_temperature`, `TARGET_LANG`). Never Qt. Never `wizard_theme`. It **never returns a hex color** — only ramp keys `"muted" | "neutral" | "green" | "warning" | "error"`.
- `wizard_theme.py` imports stdlib + `PyQt6.QtGui` only. It loads `bookweaver.json` with its own `json.load` — never imports `settings`.
- `wizard.py` must not import `tts` (probe Kokoro via `importlib.util.find_spec("kokoro")`) and must not import `llm` (probe via `find_spec("mlx_lm")`). Importing them loads torch / mlx at startup.
- `build_config()` emits **exactly 22 keys**, on both backends. Never branch the dict shape on backend.
- Environment: `uv pip install` (not `pip`, not `uv sync`). Python is `.venv/bin/python`.
- Run tests with `pytest -q`. **One pre-existing failure is expected and must not be fixed here:** `test_settings.py::TestOllamaTimeout::test_defaults_when_missing` (asserts `600`, `settings.py` defaults to `1200`).

---

## File Structure

| File | Responsibility |
|---|---|
| `bookweaver.json` | **Modify.** Add additive `wizard_colors` block. `colors` untouched. |
| `worker.py` | **Modify, 3 lines.** Plumb `max_tokens` through `config`. |
| `wizard_theme.py` | **Create.** `W_*` color constants, `RAMP`, `LOG_COLORS`, `WIZARD_STYLESHEET`, Caveat font loading. |
| `wizard_logic.py` | **Create.** `ChapterRow`, `WizardState`, enum maps, `derive_target_is_spanish`, `validation_errors`, `resume_hint`, `creativity_notch`, `creativity_readout`, `keep_pct_readout`, `recap_text`, `build_config`, `CONFIG_KEYS`. |
| `wizard_widgets.py` | **Create.** `Card`, `WizardSlider`, `ModeTileGrid`, `StepRail`, `TriStateChapterList`, `RunConsole`. |
| `wizard_steps.py` | **Create.** `StepBook`, `StepTransform`, `StepOutput`, `StepRun`. |
| `wizard.py` | **Create.** `WizardWindow` shell + entry point. |
| `assets/Caveat-Regular.ttf`, `assets/OFL.txt` | **Create.** Decorative font + license. |
| `tests/test_wizard_logic.py` | **Create.** Pure-logic unit tests. |
| `tests/test_worker.py` | **Modify.** Two tests for the `max_tokens` plumb. |
| `CLAUDE.md` | **Modify.** Update the `grep -n "^class "` guard block. |

---

## Task 1: `wizard_colors` palette + `wizard_theme` constants

**Files:**
- Modify: `bookweaver.json`
- Create: `wizard_theme.py`
- Test: `tests/test_wizard_theme.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `wizard_theme.W_APP_BG`, `W_WINDOW_BG`, `W_SURFACE`, `W_INSET`, `W_CONSOLE_BG`, `W_FOOTER_BG`, `W_BORDER`, `W_BORDER_INPUT`, `W_BORDER_STRONG`, `W_BORDER_CTRL`, `W_AMBER`, `W_AMBER_HOVER`, `W_AMBER_DIM`, `W_TEXT`, `W_TEXT_SECONDARY`, `W_MUTED`, `W_MUTED2`, `W_FAINT`, `W_FAINT2`, `W_SUCCESS`, `W_WARNING`, `W_ERROR`, `W_TILE_SELECTED`, `W_TRACK`, `W_KNOB_RING`, `W_ROW_HOVER`, `W_FILL_START`, `W_LOG_INFO`, `W_LOG_MUTED`, `W_BTN_DISABLED_BG`, `W_BTN_DISABLED_FG`, `W_DANGER_BG`, `W_DANGER_BORDER`, `W_BADGE_DONE_BG` (all `str` hex); `RAMP: dict[str, str]`; `LOG_COLORS: dict[str, str]`.

> **Spec addendum, decided here.** §6 of the spec lists 23 `wizard_colors` keys, but the design also uses 11 hexes it never named: the slider track `#2a2b24`, knob ring `#15150f`, chapter-row hover `#181812`, slider fill-gradient start and log-muted (both `#5b594f`), log-info `#9a978c`, disabled-button bg/fg `#3a3528`/`#6c6453`, danger bg/border `#23130f`/`#5a3127`, and completed-badge fill `#26271f`. Hardcoding them would violate CLAUDE.md rule #2, so all 11 are added to `wizard_colors`. `fill_start` and `log_muted` share a hex but are distinct roles and get distinct keys.

- [ ] **Step 1: Add the `wizard_colors` block to `bookweaver.json`**

Insert as a new top-level key. Do **not** touch the existing `colors` block.

```json
  "wizard_colors": {
    "app_bg":            "#0a0a08",
    "window_bg":         "#111210",
    "surface":           "#1a1b18",
    "inset":             "#0f0f0c",
    "console_bg":        "#0c0c09",
    "footer_bg":         "#16160f",
    "border":            "#2e2f2a",
    "border_input":      "#36372f",
    "border_strong":     "#3a3b34",
    "border_ctrl":       "#4a4b42",
    "amber":             "#d4a853",
    "amber_hover":       "#deb469",
    "amber_dim":         "#8a6a2e",
    "text":              "#e8e4d9",
    "text_secondary":    "#cfc9ba",
    "muted":             "#7a7870",
    "muted2":            "#8a8678",
    "faint":             "#6c6a62",
    "faint2":            "#55564d",
    "success":           "#7aab6e",
    "warning":           "#c98d3a",
    "error":             "#c0604a",
    "tile_selected":     "#211c12",
    "track":             "#2a2b24",
    "knob_ring":         "#15150f",
    "row_hover":         "#181812",
    "fill_start":        "#5b594f",
    "log_info":          "#9a978c",
    "log_muted":         "#5b594f",
    "btn_disabled_bg":   "#3a3528",
    "btn_disabled_fg":   "#6c6453",
    "danger_bg":         "#23130f",
    "danger_border":     "#5a3127",
    "badge_done_bg":     "#26271f"
  },
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_wizard_theme.py`:

```python
"""
tests/test_wizard_theme.py
--------------------------
Palette loading and semantic maps. No Qt behaviour is exercised.
"""
import json
from pathlib import Path

import pytest

import wizard_theme


CONFIG = json.loads((Path(__file__).parent.parent / "bookweaver.json").read_text())


class TestPalette:
    def test_every_json_key_becomes_a_constant(self):
        for key, hex_value in CONFIG["wizard_colors"].items():
            const = f"W_{key.upper()}"
            assert hasattr(wizard_theme, const), f"missing {const}"
            assert getattr(wizard_theme, const) == hex_value

    def test_constants_are_hex_strings(self):
        assert wizard_theme.W_AMBER == "#d4a853"
        assert wizard_theme.W_CONSOLE_BG == "#0c0c09"

    def test_old_colors_block_is_untouched(self):
        assert set(CONFIG["colors"]) == {
            "bg", "surface", "surface2", "border", "amber", "amber_dim",
            "text", "muted", "success", "warning", "error", "sweet",
        }


class TestRamp:
    def test_ramp_has_five_semantic_keys(self):
        assert set(wizard_theme.RAMP) == {
            "muted", "neutral", "green", "warning", "error"
        }

    def test_ramp_maps_to_palette_hexes(self):
        assert wizard_theme.RAMP["green"] == wizard_theme.W_SUCCESS
        assert wizard_theme.RAMP["neutral"] == wizard_theme.W_TEXT_SECONDARY
        assert wizard_theme.RAMP["error"] == wizard_theme.W_ERROR


class TestLogColors:
    def test_exactly_the_five_levels_the_worker_emits(self):
        assert set(wizard_theme.LOG_COLORS) == {
            "info", "success", "warning", "error", "muted"
        }

    def test_head_severity_is_dropped(self):
        assert "head" not in wizard_theme.LOG_COLORS

    def test_info_uses_the_designs_dimmer_hex_not_body_text(self):
        assert wizard_theme.LOG_COLORS["info"] == "#9a978c"
        assert wizard_theme.LOG_COLORS["info"] != wizard_theme.W_TEXT


class TestMissingBlock:
    def test_missing_wizard_colors_raises_systemexit(self, tmp_path):
        bad = tmp_path / "bookweaver.json"
        bad.write_text(json.dumps({"colors": {}}))
        with pytest.raises(SystemExit):
            wizard_theme._load_wizard_colors(bad)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_wizard_theme.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'wizard_theme'`

- [ ] **Step 4: Write `wizard_theme.py` (palette half only)**

The stylesheet and font come in Tasks 2 and 3. Write only what the test needs.

```python
"""
wizard_theme.py
---------------
Palette, stylesheet, and decorative font for the Guided Wizard frontend.

Loads bookweaver.json["wizard_colors"] directly rather than importing
settings.py — that module's _build() runs at import time and populates the
*old* UI's globals. Keeping the loaders separate keeps the two themes from
sharing mutable state.

Imports stdlib + PyQt6.QtGui only. Never settings, never app, never worker.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "bookweaver.json"


def _load_wizard_colors(path: Path = _CONFIG_PATH) -> dict[str, str]:
    """Return the wizard_colors block, or exit with a clear message.

    Mirrors settings._load_config's failure style: a missing or malformed
    palette is a startup error, not something to paper over with defaults.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"[BookWeaver] Config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[BookWeaver] Invalid JSON in config: {exc}")
    try:
        return cfg["wizard_colors"]
    except KeyError:
        raise SystemExit(
            f"[BookWeaver] '{path.name}' has no 'wizard_colors' block. "
            "The wizard frontend cannot start without it; see "
            "docs/superpowers/specs/2026-07-08-wizard-frontend-design.md §6."
        )


_C = _load_wizard_colors()

# Every wizard_colors key becomes a W_<UPPERCASE> module constant.
W_APP_BG          = _C["app_bg"]
W_WINDOW_BG       = _C["window_bg"]
W_SURFACE         = _C["surface"]
W_INSET           = _C["inset"]
W_CONSOLE_BG      = _C["console_bg"]
W_FOOTER_BG       = _C["footer_bg"]
W_BORDER          = _C["border"]
W_BORDER_INPUT    = _C["border_input"]
W_BORDER_STRONG   = _C["border_strong"]
W_BORDER_CTRL     = _C["border_ctrl"]
W_AMBER           = _C["amber"]
W_AMBER_HOVER     = _C["amber_hover"]
W_AMBER_DIM       = _C["amber_dim"]
W_TEXT            = _C["text"]
W_TEXT_SECONDARY  = _C["text_secondary"]
W_MUTED           = _C["muted"]
W_MUTED2          = _C["muted2"]
W_FAINT           = _C["faint"]
W_FAINT2          = _C["faint2"]
W_SUCCESS         = _C["success"]
W_WARNING         = _C["warning"]
W_ERROR           = _C["error"]
W_TILE_SELECTED   = _C["tile_selected"]
W_TRACK           = _C["track"]
W_KNOB_RING       = _C["knob_ring"]
W_ROW_HOVER       = _C["row_hover"]
W_FILL_START      = _C["fill_start"]
W_LOG_INFO        = _C["log_info"]
W_LOG_MUTED       = _C["log_muted"]
W_BTN_DISABLED_BG = _C["btn_disabled_bg"]
W_BTN_DISABLED_FG = _C["btn_disabled_fg"]
W_DANGER_BG       = _C["danger_bg"]
W_DANGER_BORDER   = _C["danger_border"]
W_BADGE_DONE_BG   = _C["badge_done_bg"]

# wizard_logic returns semantic ramp keys, never hexes. This is where they
# become colors — the single place the two halves meet.
RAMP: dict[str, str] = {
    "muted":   W_MUTED,
    "neutral": W_TEXT_SECONDARY,
    "green":   W_SUCCESS,
    "warning": W_WARNING,
    "error":   W_ERROR,
}

# Exactly the five levels ProcessingWorker.log emits (worker.py:44-45).
# The design also lists a "head" severity; nothing emits it, so it is dropped.
LOG_COLORS: dict[str, str] = {
    "info":    W_LOG_INFO,
    "muted":   W_LOG_MUTED,
    "success": W_SUCCESS,
    "warning": W_WARNING,
    "error":   W_ERROR,
}
```

Note `E221` (aligned assignments) is suppressed in `.pycodestyle` — the aligned block above is intentional and lint-clean.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_wizard_theme.py -q`
Expected: PASS (13 tests)

- [ ] **Step 6: Verify the old UI still boots**

Run: `python -c "import settings, app; print('old UI imports OK')"`
Expected: `old UI imports OK`

- [ ] **Step 7: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_theme.py
git add bookweaver.json wizard_theme.py tests/test_wizard_theme.py
git commit -m "feat(wizard): wizard_colors palette + wizard_theme constants"
```

---

## Task 2: `WIZARD_STYLESHEET`

**Files:**
- Modify: `wizard_theme.py`
- Test: `tests/test_wizard_theme.py`

**Interfaces:**
- Consumes: `wizard_theme.W_*` (Task 1).
- Produces: `wizard_theme.WIZARD_STYLESHEET: str`.

Widget object names referenced by the stylesheet, relied on by Tasks 6–14:
`#appTitle`, `#appSubtitle`, `#amberRule`, `#recapLine`, `#stepPrompt`,
`#card`, `#cardTitle`, `#cardMeta`, `#helper`, `#note`, `#footer`,
`#primaryBtn`, `#dangerBtn`, `#ghostBtn`, `#contentArea`, `#logView`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wizard_theme.py`:

```python
class TestStylesheet:
    def test_is_a_nonempty_string(self):
        assert isinstance(wizard_theme.WIZARD_STYLESHEET, str)
        assert len(wizard_theme.WIZARD_STYLESHEET) > 500

    def test_contains_no_unresolved_fstring_braces(self):
        assert "{W_" not in wizard_theme.WIZARD_STYLESHEET

    def test_references_the_wizard_palette_not_the_old_one(self):
        ss = wizard_theme.WIZARD_STYLESHEET
        assert wizard_theme.W_WINDOW_BG in ss     # #111210
        assert wizard_theme.W_FOOTER_BG in ss     # #16160f
        assert "#1c1d1b" not in ss                # old colors.surface

    def test_defines_the_object_names_the_steps_rely_on(self):
        ss = wizard_theme.WIZARD_STYLESHEET
        for name in ("#appTitle", "#card", "#primaryBtn", "#dangerBtn",
                     "#ghostBtn", "#footer", "#logView", "#recapLine"):
            assert name in ss, f"stylesheet missing {name}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wizard_theme.py::TestStylesheet -q`
Expected: FAIL — `AttributeError: module 'wizard_theme' has no attribute 'WIZARD_STYLESHEET'`

- [ ] **Step 3: Append the stylesheet to `wizard_theme.py`**

Append below `LOG_COLORS`:

```python
_MONO = '"SF Mono", ui-monospace, Menlo, monospace'
_SANS = '-apple-system, "Helvetica Neue", Helvetica, system-ui, sans-serif'

WIZARD_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {W_WINDOW_BG};
    color: {W_TEXT};
    font-family: {_SANS};
    font-size: 13px;
}}
QLabel {{ background: transparent; color: {W_TEXT}; }}

QLabel#appTitle {{
    color: {W_AMBER}; font-size: 19px; font-weight: 700; letter-spacing: -0.5px;
}}
QLabel#appSubtitle {{ color: {W_MUTED}; font-size: 12px; }}
QLabel#recapLine   {{ color: {W_FAINT}; font-size: 11px; }}
QLabel#stepPrompt  {{ color: {W_AMBER_DIM}; font-size: 16px; }}
QLabel#helper      {{ color: {W_MUTED}; font-size: 11px; }}
QLabel#cardMeta    {{ color: {W_MUTED}; font-family: {_MONO}; font-size: 11px; }}
QLabel#cardTitle   {{
    color: {W_MUTED2}; font-size: 10px; font-weight: 600; letter-spacing: 1.4px;
}}

QFrame#amberRule {{ border: none; background: {W_AMBER}; max-height: 2px; }}

QFrame#card {{
    background-color: {W_SURFACE};
    border: 1px solid {W_BORDER};
    border-radius: 9px;
}}
QFrame#note {{
    background-color: {W_INSET};
    border: 1px solid {W_BORDER};
    border-radius: 7px;
}}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {W_INSET};
    border: 1px solid {W_BORDER_INPUT};
    border-radius: 7px;
    padding: 9px 11px;
    color: {W_TEXT};
    font-family: {_MONO};
    font-size: 12px;
    selection-background-color: {W_AMBER_DIM};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {W_AMBER}; }}
QComboBox:hover, QSpinBox:hover {{ border-color: {W_FAINT2}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {W_MUTED};
    margin-right: 7px;
}}
QComboBox QAbstractItemView {{
    background-color: {W_SURFACE};
    border: 1px solid {W_BORDER};
    selection-background-color: {W_AMBER_DIM};
    color: {W_TEXT};
    padding: 4px;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {W_BTN_DISABLED_FG};
    border-color: {W_BORDER};
}}

QPushButton {{
    background: transparent;
    border: 1px solid {W_BORDER_STRONG};
    border-radius: 7px;
    padding: 8px 13px;
    color: {W_TEXT_SECONDARY};
}}
QPushButton:hover {{ border-color: {W_FAINT2}; color: {W_TEXT}; }}

QPushButton#primaryBtn {{
    background-color: {W_AMBER}; border: none;
    color: {W_WINDOW_BG}; font-weight: 600;
}}
QPushButton#primaryBtn:hover    {{ background-color: {W_AMBER_HOVER}; }}
QPushButton#primaryBtn:disabled {{
    background-color: {W_BTN_DISABLED_BG}; color: {W_BTN_DISABLED_FG};
}}

QPushButton#dangerBtn {{
    background-color: {W_DANGER_BG};
    border: 1px solid {W_DANGER_BORDER};
    color: {W_ERROR};
}}
QPushButton#dangerBtn:disabled {{ color: {W_DANGER_BORDER}; }}

QPushButton#ghostBtn {{ background: transparent; border: none; color: {W_MUTED}; }}
QPushButton#ghostBtn:hover {{ color: {W_TEXT}; }}

QWidget#footer {{
    background-color: {W_FOOTER_BG};
    border-top: 1px solid {W_BORDER};
}}

QTextEdit#logView {{
    background-color: {W_CONSOLE_BG};
    border: 1px solid {W_BORDER};
    border-radius: 9px;
    padding: 13px 15px;
    color: {W_LOG_INFO};
    font-family: {_MONO};
    font-size: 12px;
}}

QCheckBox, QRadioButton {{ spacing: 8px; color: {W_TEXT}; background: transparent; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1.5px solid {W_BORDER_CTRL}; background: {W_INSET};
}}
QCheckBox::indicator:checked {{
    background-color: {W_AMBER}; border-color: {W_AMBER};
}}
QCheckBox::indicator:indeterminate {{
    background-color: {W_BTN_DISABLED_BG}; border-color: {W_AMBER_DIM};
}}
QCheckBox::indicator:disabled {{ border-color: {W_BORDER}; background: {W_WINDOW_BG}; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {W_AMBER_DIM}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wizard_theme.py -q`
Expected: PASS (17 tests)

- [ ] **Step 5: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_theme.py
git add wizard_theme.py tests/test_wizard_theme.py
git commit -m "feat(wizard): WIZARD_STYLESHEET"
```

---

## Task 3: Caveat decorative font

**Files:**
- Create: `assets/Caveat-Regular.ttf`, `assets/OFL.txt`
- Modify: `wizard_theme.py`
- Test: `tests/test_wizard_theme.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `wizard_theme.load_caveat() -> str | None` — returns the loaded family name, or `None` when the asset is absent or unparseable. Callers fall back to muted italic system font.

> **Why the static instance:** Google ships `Caveat[wght].ttf` as a *variable* font. `QFontDatabase.addApplicationFont` accepts it but selecting a single weight through Qt is unreliable. Fetch the static instance instead — it lives under `ofl/caveat/static/` in the `google/fonts` repo.

- [ ] **Step 1: Fetch the font and its license**

```bash
mkdir -p assets
curl -fL -o assets/Caveat-Regular.ttf \
  https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/static/Caveat-Regular.ttf
curl -fL -o assets/OFL.txt \
  https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/OFL.txt
```

Verify it is a real TrueType file, not an HTML 404 page:

```bash
file assets/Caveat-Regular.ttf
```
Expected: `assets/Caveat-Regular.ttf: TrueType Font data, ...`

If the `static/` path 404s, fall back to the variable font and note it:
`curl -fL -o assets/Caveat-Regular.ttf https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/Caveat%5Bwght%5D.ttf`

- [ ] **Step 2: Write the failing test**

Append to `tests/test_wizard_theme.py`:

```python
class TestCaveat:
    def test_asset_exists_and_is_truetype(self):
        ttf = Path(__file__).parent.parent / "assets" / "Caveat-Regular.ttf"
        assert ttf.exists(), "run the curl in Task 3 Step 1"
        # 0x00010000 (TrueType) or "OTTO" (CFF). Never "<!DO" (an HTML 404).
        assert ttf.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true")

    def test_license_is_committed(self):
        assert (Path(__file__).parent.parent / "assets" / "OFL.txt").exists()

    def test_load_caveat_returns_none_for_a_missing_file(self, tmp_path):
        assert wizard_theme.load_caveat(tmp_path / "nope.ttf") is None

    def test_load_caveat_returns_none_for_a_bogus_file(self, tmp_path):
        bad = tmp_path / "bad.ttf"
        bad.write_text("<!DOCTYPE html><html>404</html>")
        assert wizard_theme.load_caveat(bad) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_wizard_theme.py::TestCaveat -q`
Expected: FAIL — `AttributeError: module 'wizard_theme' has no attribute 'load_caveat'`
(`test_asset_exists_and_is_truetype` should already PASS from Step 1.)

- [ ] **Step 4: Add `load_caveat` to `wizard_theme.py`**

Append. Note the import is inside the function — importing `QtGui` at module scope would make `wizard_theme` unimportable in a headless test run.

```python
CAVEAT_PATH = Path(__file__).parent / "assets" / "Caveat-Regular.ttf"


def load_caveat(path: Path = CAVEAT_PATH) -> str | None:
    """Register the decorative Caveat font; return its family name.

    Returns None when the asset is missing or unparseable — a fresh clone
    without assets/ must never crash. Callers fall back to muted italic
    system font for the per-step prompts, which are purely cosmetic.
    """
    if not Path(path).exists():
        return None
    from PyQt6.QtGui import QFontDatabase
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id == -1:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_wizard_theme.py -q`
Expected: PASS (21 tests)

- [ ] **Step 6: Commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_theme.py
git add assets wizard_theme.py tests/test_wizard_theme.py
git commit -m "feat(wizard): bundle Caveat (OFL) + graceful font loading"
```

---

## Task 4: `worker.py` — plumb `max_tokens` through config

**Files:**
- Modify: `worker.py:56-67` (`__init__`), `worker.py:123`, `worker.py:916`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProcessingWorker._max_tokens: int`. `ProcessingWorker` now honors a `max_tokens` key in its config dict, defaulting to `SETTINGS["mlx_max_tokens"]` when absent.

> Backward compatibility is the whole point: `app.py:_build_config` never sets `max_tokens`, so the old UI keeps the `bookweaver.json` default and its behavior is bit-for-bit unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`:

```python
# ──────────────────────────────────────────────────────────────
#  max_tokens plumbing (config override with SETTINGS fallback)
# ──────────────────────────────────────────────────────────────
class TestMaxTokensPlumbing:
    def test_absent_key_falls_back_to_settings(self):
        """app.py never sets max_tokens — it must keep the JSON default."""
        w = _make_worker()
        assert w._max_tokens == SETTINGS.get("mlx_max_tokens", 8192)

    def test_config_key_overrides_settings(self):
        w = _make_worker({"epub_path": "/tmp/f.epub", "max_tokens": 512})
        assert w._max_tokens == 512

    def test_llm_call_passes_the_instance_attribute(self):
        w = _make_worker()
        w._max_tokens = 1234
        with patch("llm.generate", return_value="ok") as gen:
            w._llm_call("m", "p", label="L", temperature=0.5)
        assert gen.call_args[1]["max_tokens"] == 1234
```

`_make_worker(config)` (defined at `tests/test_worker.py:128`) passes the dict
straight to `ProcessingWorker(config)`, so the override test exercises the real
`__init__`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py::TestMaxTokensPlumbing -q`
Expected: FAIL — `AttributeError: 'ProcessingWorker' object has no attribute '_max_tokens'`

- [ ] **Step 3: Make the three edits**

Edit 1 — `worker.py`, in `__init__`, immediately after the `self._backend` assignment (currently ends at line 64):

```python
        self._backend = config.get(
            "backend", SETTINGS.get("llm_backend", "ollama")
        )
        self._max_tokens = config.get(
            "max_tokens", SETTINGS.get("mlx_max_tokens", 8192)
        )
```

Edit 2 — `worker.py:123`. Was:

```python
                f"at {SETTINGS.get('mlx_max_tokens', 8192)} tokens.",
```

Now:

```python
                f"at {self._max_tokens} tokens.",
```

Edit 3 — `worker.py:916`, inside `_llm_call`. Was:

```python
            max_tokens=SETTINGS.get("mlx_max_tokens", 8192),
```

Now:

```python
            max_tokens=self._max_tokens,
```

**Both** `SETTINGS` reads must change. Fixing only `_llm_call` leaves the
`ℹ️ mlx backend: … output capped at N tokens.` log line reporting the JSON
default while the worker actually uses the config value.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py -q`
Expected: PASS (all worker tests, including the pre-existing `_llm_call` delegation test)

- [ ] **Step 5: Prove the old UI is unaffected**

Run:
```bash
python - <<'EOF'
import worker
from settings import SETTINGS
# app.py's config shape: 21 keys, never max_tokens.
cfg = {"epub_path": "/tmp/x.epub", "timeout": 1200, "chunk_size": 2000}
w = worker.ProcessingWorker(cfg)
assert w._max_tokens == SETTINGS["mlx_max_tokens"], w._max_tokens
assert w._timeout == 1200
print("old-UI config path OK:", w._max_tokens)
EOF
```
Expected: `old-UI config path OK: 8192`

(Constructing a `ProcessingWorker` outside a `QApplication` is safe — `QThread.__init__` needs no event loop, and no signal is emitted here.)

- [ ] **Step 6: Full suite + lint + commit**

```bash
pytest -q     # 1 pre-existing failure expected: test_settings TestOllamaTimeout
pycodestyle --config=.pycodestyle --statistics worker.py
git add worker.py tests/test_worker.py
git commit -m "feat(worker): honor config['max_tokens'], falling back to SETTINGS"
```

---

## Task 5: `wizard_logic.py` — state, enums, and derivations

**Files:**
- Create: `wizard_logic.py`
- Test: `tests/test_wizard_logic.py`

**Interfaces:**
- Consumes: `settings.creativity_to_temperature`, `settings.TARGET_LANG`.
- Produces:
  - `ChapterRow(index: int, title: str, checked: bool = True)` — frozen dataclass
  - `WizardState` — mutable dataclass, all fields defaulted
  - `MODES: tuple[str, ...]` = `("sr", "full", "sum", "key")`
  - `MODE_TO_WORKER: dict[str, str]`, `CARRY_TO_WORKER: dict[str, str]`
  - `CONFIG_KEYS: frozenset[str]` — the 22 keys
  - `derive_target_is_spanish(mode: str, key_ideas_lang: str) -> bool`
  - `validation_errors(state: WizardState) -> list[tuple[int, str]]`
  - `resume_hint(backend: str) -> str`
  - `creativity_notch(n: int) -> tuple[str, str]` — `(name, ramp_key)`
  - `creativity_readout(n: int) -> str`
  - `keep_pct_readout(pct: int) -> tuple[str, bool]` — `(text, is_sweet)`
  - `recap_text(state: WizardState, model_label: str) -> str`
  - `build_config(state: WizardState, backend: str) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wizard_logic.py`:

```python
"""
tests/test_wizard_logic.py
--------------------------
wizard_logic.py is pure Python — no Qt, no palette. Everything here runs
without a QApplication.
"""
from pathlib import Path

import pytest

import wizard_logic as wl
from settings import creativity_to_temperature


def _state(**over) -> wl.WizardState:
    """A valid, startable state. Override any field by keyword."""
    base = wl.WizardState(
        epub_path="/books/middlemarch.epub",
        chapters=[wl.ChapterRow(i, f"Chapter {i + 1}") for i in range(11)],
        model="mlx-community/gemma-4-31B-it-qat-8bit",
        out_folder="/books/out",
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


# ── derive_target_is_spanish ───────────────────────────────────
class TestDeriveTargetIsSpanish:
    @pytest.mark.parametrize("lang", ["es", "en"])
    def test_summarise_rewrite_is_always_spanish(self, lang):
        assert wl.derive_target_is_spanish("sr", lang) is True

    @pytest.mark.parametrize("lang", ["es", "en"])
    def test_full_translation_is_always_spanish(self, lang):
        assert wl.derive_target_is_spanish("full", lang) is True

    @pytest.mark.parametrize("lang", ["es", "en"])
    def test_summarise_only_is_never_spanish(self, lang):
        assert wl.derive_target_is_spanish("sum", lang) is False

    def test_key_ideas_follows_its_language_toggle(self):
        assert wl.derive_target_is_spanish("key", "es") is True
        assert wl.derive_target_is_spanish("key", "en") is False


# ── validation_errors ──────────────────────────────────────────
class TestValidationErrors:
    def test_valid_state_has_no_errors(self):
        assert wl.validation_errors(_state()) == []

    def test_empty_state_flags_file_and_format(self):
        errs = wl.validation_errors(wl.WizardState())
        assert (1, "Select an EPUB file") in errs
        # No file => the chapter check is suppressed, not doubled up.
        assert not any("chapter" in m for _, m in errs)

    def test_no_chapters_ticked_flags_step_one(self):
        s = _state(chapters=[wl.ChapterRow(0, "One", checked=False)])
        assert wl.validation_errors(s) == [(1, "Select at least one chapter")]

    def test_no_format_flags_step_three(self):
        s = _state(formats={"txt": False, "epub": False, "html": False})
        assert wl.validation_errors(s) == [
            (3, "Select at least one output format")
        ]

    def test_multiple_problems_are_all_reported(self):
        s = _state(
            chapters=[wl.ChapterRow(0, "One", checked=False)],
            formats={"txt": False, "epub": False, "html": False},
        )
        assert {step for step, _ in wl.validation_errors(s)} == {1, 3}


# ── resume_hint ────────────────────────────────────────────────
class TestResumeHint:
    def test_ollama_mentions_the_timeout(self):
        assert wl.resume_hint("ollama") == "Raise the timeout, then press Resume."

    def test_mlx_does_not_mention_the_timeout(self):
        hint = wl.resume_hint("mlx")
        assert hint == "Adjust settings, then press Resume."
        assert "timeout" not in hint.lower()


# ── creativity ─────────────────────────────────────────────────
class TestCreativityNotch:
    def test_all_ten_notches_are_named(self):
        names = [wl.creativity_notch(n)[0] for n in range(1, 11)]
        assert names == [
            "Verbatim", "Faithful", "Faithful+", "Enriched", "Enriched+",
            "Vivid", "Expressive", "Inventive", "Free", "Unbound",
        ]

    def test_ramp_follows_the_design_not_widgets_py(self):
        """Design: 1-2 muted, 3-4 neutral, 5-6 green, 7-8 warning, 9-10 error.
        widgets.py has 7-8 brand-amber and 9 warning — we do not copy it."""
        ramp = [wl.creativity_notch(n)[1] for n in range(1, 11)]
        assert ramp == [
            "muted", "muted", "neutral", "neutral", "green",
            "green", "warning", "warning", "error", "error",
        ]

    def test_ramp_keys_are_never_hex(self):
        for n in range(1, 11):
            assert not wl.creativity_notch(n)[1].startswith("#")


class TestCreativityReadout:
    def test_uses_the_real_temperature_function_not_the_mockups(self):
        """The design's mockup showed 0.44 at level 5, using (N-1)/9.
        settings.creativity_to_temperature is what the worker actually
        passes to the model: 0.1 + (N-1)*(1.3/9) = 0.68."""
        assert creativity_to_temperature(5) == 0.68
        out = wl.creativity_readout(5)
        assert "0.68" in out
        assert "0.44" not in out

    def test_format(self):
        assert wl.creativity_readout(5) == "Enriched+ — level 5/10  (temp ≈ 0.68)"

    def test_every_level_renders(self):
        for n in range(1, 11):
            assert f"level {n}/10" in wl.creativity_readout(n)


# ── keep_pct_readout ───────────────────────────────────────────
class TestKeepPctReadout:
    @pytest.mark.parametrize("pct,sweet", [
        (10, False), (29, False), (30, True), (40, True),
        (50, True), (51, False), (90, False),
    ])
    def test_sweet_spot_boundaries_are_30_to_50_inclusive(self, pct, sweet):
        assert wl.keep_pct_readout(pct)[1] is sweet

    def test_text_reports_keep_and_reduction(self):
        text, _ = wl.keep_pct_readout(40)
        assert text == "Keep 40% of original (↓ 60% reduction)"


# ── recap_text ─────────────────────────────────────────────────
class TestRecapText:
    LABEL = "Gemma 4 31B QAT (recommended)"

    def test_all_selected_omits_the_fraction(self):
        out = wl.recap_text(_state(), self.LABEL)
        assert "11 chapters" in out
        assert "/" not in out.split("chapters")[0]

    def test_partial_selection_shows_the_fraction(self):
        rows = [wl.ChapterRow(i, f"C{i}", checked=i < 3) for i in range(11)]
        out = wl.recap_text(_state(chapters=rows), self.LABEL)
        assert "3 / 11 chapters" in out

    def test_model_label_is_truncated_at_the_parenthesis(self):
        out = wl.recap_text(_state(), self.LABEL)
        assert "Gemma 4 31B QAT" in out
        assert "recommended" not in out

    def test_level_shown_when_output_is_spanish(self):
        assert wl.recap_text(_state(mode="sr"), self.LABEL).endswith("B2")

    def test_level_omitted_when_output_is_english(self):
        out = wl.recap_text(_state(mode="sum"), self.LABEL)
        assert "B2" not in out

    def test_key_ideas_english_omits_the_level(self):
        out = wl.recap_text(_state(mode="key", key_ideas_lang="en"), self.LABEL)
        assert "B2" not in out

    def test_starts_with_step_1_and_the_filename(self):
        out = wl.recap_text(_state(), self.LABEL)
        assert out.startswith("Step 1 · middlemarch.epub · ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wizard_logic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'wizard_logic'`

- [ ] **Step 3: Write `wizard_logic.py` (everything but `build_config`)**

```python
"""
wizard_logic.py
---------------
Pure, Qt-free decision logic for the Guided Wizard frontend.

This is the only load-bearing wizard module: build_config() is the single
seam where a cosmetic rewrite could silently break the pipeline. Everything
here is unit-tested.

Imports stdlib + settings only. Never Qt, never wizard_theme, never app or
worker. In particular it NEVER returns a hex colour — only semantic ramp
keys, which wizard_widgets maps to W_* constants. That is what keeps this
module testable without a QApplication or a palette.
"""

from dataclasses import dataclass, field
from pathlib import Path

from settings import TARGET_LANG, creativity_to_temperature

# ──────────────────────────────────────────────────────────────
#  Vocabulary
# ──────────────────────────────────────────────────────────────
MODES: tuple[str, ...] = ("sr", "full", "sum", "key")

# The design's state names are short; the worker's are explicit.
MODE_TO_WORKER: dict[str, str] = {
    "sr":   "summarise_rewrite",
    "full": "translate",
    "sum":  "summarise_only",
    "key":  "summarise_key_ideas",
}

# Likewise for cross-chunk continuity (worker.py reads carry_mode).
CARRY_TO_WORKER: dict[str, str] = {
    "off":   "off",
    "names": "glossary",
    "tail":  "prose",
    "both":  "both",
}

# Exactly what ProcessingWorker._run() reads. app.py emits the first 21;
# max_tokens is the wizard's addition (see worker.py __init__).
CONFIG_KEYS: frozenset[str] = frozenset({
    "epub_path", "model", "backend", "selected_chapters", "mode", "level",
    "keep_pct", "creativity", "carry_mode", "summary_lang", "target_lang",
    "out_format", "out_folder", "generate_mp3", "voice",
    "meta_title", "meta_creator", "meta_language", "meta_contributor",
    "chunk_size", "timeout", "max_tokens",
})

KEEP_SWEET_MIN, KEEP_SWEET_MAX = 30, 50
CREATIVITY_SWEET_MIN, CREATIVITY_SWEET_MAX = 5, 6

# (name, ramp_key). Ramp per the handoff README: 1-2 muted, 3-4 neutral,
# 5-6 green, 7-8 warning, 9-10 error. widgets.py's older ramp puts 7-8 on
# brand amber and 9 on warning; the wizard does not copy it.
CREATIVITY_NOTCHES: dict[int, tuple[str, str]] = {
    1:  ("Verbatim",   "muted"),
    2:  ("Faithful",   "muted"),
    3:  ("Faithful+",  "neutral"),
    4:  ("Enriched",   "neutral"),
    5:  ("Enriched+",  "green"),
    6:  ("Vivid",      "green"),
    7:  ("Expressive", "warning"),
    8:  ("Inventive",  "warning"),
    9:  ("Free",       "error"),
    10: ("Unbound",    "error"),
}


# ──────────────────────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ChapterRow:
    """One row of the Step-1 chapter checklist.

    `index` is epub_io.Chapter.index — the stable 0-based document position,
    which is what worker.select_chapters() filters on. It is NOT the row's
    position in this list.
    """
    index: int
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


# ──────────────────────────────────────────────────────────────
#  Derivations
# ──────────────────────────────────────────────────────────────
def derive_target_is_spanish(mode: str, key_ideas_lang: str) -> bool:
    """True when the run produces Spanish text.

    There is no explicit target-language picker: it falls out of the mode,
    and for key-ideas out of that mode's own language toggle. Gates the
    Step-2 Spanish-level card, the recap line's level segment, and which
    voice list Step 3 populates.
    """
    return mode in ("sr", "full") or (mode == "key" and key_ideas_lang == "es")


def validation_errors(state: WizardState) -> list[tuple[int, str]]:
    """Return (step_number, message) for each unmet start requirement.

    One source of truth for three consumers: Start's enabled state, Start's
    tooltip, and the error decoration on the step-rail badges.
    """
    errs: list[tuple[int, str]] = []
    if not state.epub_path:
        errs.append((1, "Select an EPUB file"))
    elif not any(row.checked for row in state.chapters):
        # Only meaningful once a book is loaded — otherwise it double-reports.
        errs.append((1, "Select at least one chapter"))
    if not any(state.formats.values()):
        errs.append((3, "Select at least one output format"))
    return errs


def resume_hint(backend: str) -> str:
    """Recovery copy for the 💾 log line after a resumable failure.

    On mlx there is no timeout to raise: generation runs in-process and is
    bounded by max_tokens instead.
    """
    if backend == "ollama":
        return "Raise the timeout, then press Resume."
    return "Adjust settings, then press Resume."


def creativity_notch(n: int) -> tuple[str, str]:
    """(display name, ramp key) for creativity level *n* (1-10)."""
    return CREATIVITY_NOTCHES[n]


def creativity_readout(n: int) -> str:
    """e.g. 'Enriched+ — level 5/10  (temp ≈ 0.68)'.

    The temperature comes from settings.creativity_to_temperature — the very
    function worker.py passes to the model. The handoff mockup showed 0.44,
    computed as (n-1)/9; that formula is not what the pipeline uses and is
    not reproduced here.
    """
    name, _ = CREATIVITY_NOTCHES[n]
    return f"{name} — level {n}/10  (temp ≈ {creativity_to_temperature(n)})"


def is_creativity_sweet(n: int) -> bool:
    return CREATIVITY_SWEET_MIN <= n <= CREATIVITY_SWEET_MAX


def keep_pct_readout(pct: int) -> tuple[str, bool]:
    """(readout text, is_sweet_spot) for the summarisation-depth slider."""
    text = f"Keep {pct}% of original (↓ {100 - pct}% reduction)"
    return text, KEEP_SWEET_MIN <= pct <= KEEP_SWEET_MAX


def recap_text(state: WizardState, model_label: str) -> str:
    """The one-line step-1 recap shown from step 2 onward.

    Shows the real selection ('3 / 11 chapters'), collapsing to a bare count
    when everything is ticked. The model's config label is truncated at its
    first parenthesis so '(recommended)' does not eat the line. The CEFR
    level appears only when the run actually produces Spanish.
    """
    total = len(state.chapters)
    selected = sum(1 for row in state.chapters if row.checked)
    chapters = (
        f"{total} chapters" if selected == total
        else f"{selected} / {total} chapters"
    )
    parts = [
        "Step 1",
        Path(state.epub_path).name,
        chapters,
        model_label.split("(")[0].strip(),
    ]
    if derive_target_is_spanish(state.mode, state.key_ideas_lang):
        parts.append(state.cefr_level)
    return " · ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wizard_logic.py -q`
Expected: PASS (30 tests)

- [ ] **Step 5: Verify `wizard_logic` is genuinely Qt-free**

Run:
```bash
python -c "
import sys, wizard_logic
qt = [m for m in sys.modules if m.startswith('PyQt6')]
assert not qt, f'wizard_logic dragged in Qt: {qt}'
print('wizard_logic is Qt-free')"
```
Expected: `wizard_logic is Qt-free`

- [ ] **Step 6: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_logic.py
git add wizard_logic.py tests/test_wizard_logic.py
git commit -m "feat(wizard): pure state + derivations in wizard_logic"
```

---

## Task 6: `build_config` — the 22-key contract

**Files:**
- Modify: `wizard_logic.py`
- Test: `tests/test_wizard_logic.py`

**Interfaces:**
- Consumes: `WizardState`, `MODE_TO_WORKER`, `CARRY_TO_WORKER`, `CONFIG_KEYS`, `settings.TARGET_LANG` (Task 5).
- Produces: `build_config(state: WizardState, backend: str) -> dict` with exactly `CONFIG_KEYS`.

> This is the task that can silently break the pipeline. The key-set regression test is not optional.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wizard_logic.py`:

```python
# ── build_config: the contract with ProcessingWorker ───────────
class TestBuildConfig:
    def test_emits_exactly_the_22_contract_keys(self):
        cfg = wl.build_config(_state(), "mlx")
        assert set(cfg) == wl.CONFIG_KEYS
        assert len(wl.CONFIG_KEYS) == 22

    def test_key_set_is_identical_on_both_backends(self):
        """Dict shape must not branch on backend — resume spreads **config."""
        assert set(wl.build_config(_state(), "mlx")) == \
               set(wl.build_config(_state(), "ollama"))

    def test_covers_every_key_app_py_emits(self):
        """The wizard is a superset of app.py's 21 keys, plus max_tokens."""
        app_keys = {
            "epub_path", "level", "keep_pct", "model", "backend", "out_format",
            "out_folder", "selected_chapters", "creativity", "mode",
            "chunk_size", "carry_mode", "meta_title", "meta_creator",
            "meta_language", "meta_contributor", "timeout", "generate_mp3",
            "voice", "summary_lang", "target_lang",
        }
        assert app_keys < wl.CONFIG_KEYS
        assert wl.CONFIG_KEYS - app_keys == {"max_tokens"}

    # ── enum translation ──
    @pytest.mark.parametrize("ui,worker", [
        ("sr", "summarise_rewrite"), ("full", "translate"),
        ("sum", "summarise_only"), ("key", "summarise_key_ideas"),
    ])
    def test_mode_is_translated_to_the_workers_vocabulary(self, ui, worker):
        assert wl.build_config(_state(mode=ui), "mlx")["mode"] == worker

    @pytest.mark.parametrize("ui,worker", [
        ("off", "off"), ("names", "glossary"),
        ("tail", "prose"), ("both", "both"),
    ])
    def test_carry_is_translated_to_the_workers_vocabulary(self, ui, worker):
        assert wl.build_config(_state(carry=ui), "mlx")["carry_mode"] == worker

    # ── target_lang derivation ──
    def test_target_lang_for_key_ideas_follows_the_toggle(self):
        assert wl.build_config(
            _state(mode="key", key_ideas_lang="en"), "mlx")["target_lang"] == "en"
        assert wl.build_config(
            _state(mode="key", key_ideas_lang="es"), "mlx")["target_lang"] == "es"

    def test_target_lang_for_other_modes_comes_from_settings(self):
        assert wl.build_config(_state(mode="sr"), "mlx")["target_lang"] == "es"
        assert wl.build_config(_state(mode="full"), "mlx")["target_lang"] == "es"
        assert wl.build_config(_state(mode="sum"), "mlx")["target_lang"] == "en"

    def test_key_ideas_language_does_not_leak_into_other_modes(self):
        cfg = wl.build_config(_state(mode="sum", key_ideas_lang="es"), "mlx")
        assert cfg["target_lang"] == "en"

    # ── the rest of the mapping ──
    def test_selected_chapters_uses_chapter_index_not_row_position(self):
        rows = [wl.ChapterRow(5, "F", True), wl.ChapterRow(9, "J", False),
                wl.ChapterRow(12, "M", True)]
        cfg = wl.build_config(_state(chapters=rows), "mlx")
        assert cfg["selected_chapters"] == [5, 12]

    def test_out_format_is_an_ordered_list(self):
        s = _state(formats={"txt": True, "epub": False, "html": True})
        assert wl.build_config(s, "mlx")["out_format"] == ["txt", "html"]

    def test_out_folder_falls_back_to_the_books_directory(self):
        s = _state(out_folder="")
        assert wl.build_config(s, "mlx")["out_folder"] == "/books"

    def test_voice_is_none_when_mp3_is_off(self):
        s = _state(mp3_enabled=False, voice="ef_dora")
        assert wl.build_config(s, "mlx")["voice"] is None

    def test_voice_survives_when_mp3_is_on(self):
        s = _state(mp3_enabled=True, voice="ef_dora")
        assert wl.build_config(s, "mlx")["voice"] == "ef_dora"

    def test_meta_language_defaults_to_es_when_blank(self):
        assert wl.build_config(_state(meta_language="  "), "mlx")["meta_language"] == "es"

    def test_meta_fields_are_flat_not_nested(self):
        cfg = wl.build_config(_state(meta_title=" Middlemarch "), "mlx")
        assert cfg["meta_title"] == "Middlemarch"
        assert "epub_meta" not in cfg

    def test_backend_is_the_argument_not_a_settings_read(self):
        assert wl.build_config(_state(), "ollama")["backend"] == "ollama"

    def test_both_timeout_and_max_tokens_are_always_present(self):
        for backend in ("mlx", "ollama"):
            cfg = wl.build_config(_state(timeout_sec=900, max_tokens=4096), backend)
            assert cfg["timeout"] == 900
            assert cfg["max_tokens"] == 4096

    def test_chunk_words_maps_to_chunk_size(self):
        assert wl.build_config(_state(chunk_words=1500), "mlx")["chunk_size"] == 1500
```

Also append a live cross-check against the worker's real reads:

```python
class TestContractAgainstTheRealWorker:
    def test_worker_accepts_a_wizard_config(self):
        """Constructing ProcessingWorker with our dict must not KeyError."""
        from worker import ProcessingWorker
        cfg = wl.build_config(_state(max_tokens=2048, timeout_sec=99), "mlx")
        w = ProcessingWorker(cfg)
        assert w._max_tokens == 2048
        assert w._timeout == 99
        assert w._chunk_size == cfg["chunk_size"]
        assert w._backend == "mlx"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wizard_logic.py -k BuildConfig -q`
Expected: FAIL — `AttributeError: module 'wizard_logic' has no attribute 'build_config'`

- [ ] **Step 3: Append `build_config` to `wizard_logic.py`**

```python
def build_config(state: WizardState, backend: str) -> dict:
    """Translate WizardState into ProcessingWorker's config dict.

    Emits all 22 keys on both backends. The dict shape must never branch on
    backend: _on_resume() spreads **config, and a shape that varies would
    make the resume path backend-dependent. The worker simply ignores the
    key its backend does not use (self._timeout is unread on mlx,
    self._max_tokens on ollama).

    *backend* is passed in rather than read from SETTINGS so the caller can
    capture it once at Start and resume can never flip backends mid-book.
    """
    worker_mode = MODE_TO_WORKER[state.mode]
    summary_lang = state.key_ideas_lang
    target_lang = (
        summary_lang if worker_mode == "summarise_key_ideas"
        else TARGET_LANG[worker_mode]
    )
    return {
        "epub_path":         state.epub_path,
        "model":             state.model,
        "backend":           backend,
        "selected_chapters": [r.index for r in state.chapters if r.checked],
        "mode":              worker_mode,
        "level":             state.cefr_level,
        "keep_pct":          state.keep_pct,
        "creativity":        state.creativity,
        "carry_mode":        CARRY_TO_WORKER[state.carry],
        "summary_lang":      summary_lang,
        "target_lang":       target_lang,
        "out_format":        [f for f in ("txt", "epub", "html")
                              if state.formats.get(f)],
        "out_folder":        state.out_folder or str(Path(state.epub_path).parent),
        "generate_mp3":      state.mp3_enabled,
        "voice":             state.voice if state.mp3_enabled else None,
        "meta_title":        state.meta_title.strip(),
        "meta_creator":      state.meta_creator.strip(),
        "meta_language":     state.meta_language.strip() or "es",
        "meta_contributor":  state.meta_contributor.strip(),
        "chunk_size":        state.chunk_words,
        "timeout":           state.timeout_sec,
        "max_tokens":        state.max_tokens,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wizard_logic.py -q`
Expected: PASS (~52 tests)

- [ ] **Step 5: Full suite + lint + commit**

```bash
pytest -q     # 1 pre-existing failure expected
pycodestyle --config=.pycodestyle --statistics wizard_logic.py
git add wizard_logic.py tests/test_wizard_logic.py
git commit -m "feat(wizard): build_config — the 22-key worker contract"
```

---

## Task 7: `Card` + `RunConsole` primitives

**Files:**
- Create: `wizard_widgets.py`

**Interfaces:**
- Consumes: `wizard_theme.W_*`, `LOG_COLORS`.
- Produces:
  - `Card(title: str, meta: str = "") -> QFrame` with `.body: QVBoxLayout` and `.set_meta(text: str)`
  - `RunConsole(QWidget)` with `.append(msg: str, level: str = "info")`, `.clear_log()`, `.set_progress(current: int, total: int)`, `.reset()`

- [ ] **Step 1: Create `wizard_widgets.py` with `Card` and `RunConsole`**

```python
"""
wizard_widgets.py
-----------------
Custom-painted, reusable widgets for the Guided Wizard frontend.

Imports wizard_theme (for W_* colours) and wizard_logic (for ramp keys and
readout text) only. Never settings, never app, never worker.

widgets.py is the OLD UI's widget module and is not touched, imported, or
subclassed here.
"""

import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from wizard_theme import (
    LOG_COLORS, RAMP, W_AMBER, W_AMBER_DIM, W_BORDER, W_CONSOLE_BG, W_FAINT2,
    W_INSET, W_KNOB_RING, W_MUTED, W_SURFACE, W_TEXT, W_TILE_SELECTED,
    W_TRACK, W_FILL_START, W_BORDER_CTRL, W_BADGE_DONE_BG, W_ERROR,
    W_TEXT_SECONDARY, W_ROW_HOVER,
)


class Card(QFrame):
    """The repeated group container: uppercase title row + a body layout."""

    def __init__(self, title: str, meta: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 13, 14, 13)
        outer.setSpacing(11)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel(title.upper())
        title_lbl.setObjectName("cardTitle")
        head.addWidget(title_lbl)
        head.addStretch()
        self._meta = QLabel(meta)
        self._meta.setObjectName("cardMeta")
        head.addWidget(self._meta)
        outer.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(9)
        outer.addLayout(self.body)

    def set_meta(self, text: str) -> None:
        self._meta.setText(text)


class _ProgressPill(QWidget):
    """8px pill with rounded caps; fill is an amber-dim → amber gradient."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fraction = 0.0

    def set_fraction(self, f: float) -> None:
        self._fraction = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _event) -> None:      # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.rect()
        p.setBrush(QColor(W_TRACK))
        p.drawRoundedRect(r, 4, 4)
        if self._fraction <= 0:
            return
        fill = r.adjusted(0, 0, -int(r.width() * (1 - self._fraction)), 0)
        grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
        grad.setColorAt(0.0, QColor(W_AMBER_DIM))
        grad.setColorAt(1.0, QColor(W_AMBER))
        p.setBrush(grad)
        p.drawRoundedRect(fill, 4, 4)


class RunConsole(QWidget):
    """Progress pill + % readout + the colour-coded, auto-scrolling log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)

        header = QLabel("RUN CONSOLE")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        self._pill = _ProgressPill()
        row.addWidget(self._pill, 1)
        self._pct = QLabel("0%")
        self._pct.setObjectName("cardMeta")
        self._pct.setFixedWidth(44)
        self._pct.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._pct)
        layout.addLayout(row)

        self._log = QTextEdit()
        self._log.setObjectName("logView")
        self._log.setReadOnly(True)
        layout.addWidget(self._log, 1)

    def append(self, msg: str, level: str = "info") -> None:
        """Append one colour-coded line. Unknown levels fall back to info."""
        colour = LOG_COLORS.get(level, LOG_COLORS["info"])
        safe = html.escape(msg).replace("\n", "<br>")
        self._log.append(
            f'<span style="color:{colour}; line-height:1.7">{safe}</span>'
        )
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self._log.clear()

    def set_progress(self, current: int, total: int) -> None:
        fraction = (current / total) if total else 0.0
        self._pill.set_fraction(fraction)
        self._pct.setText(f"{round(fraction * 100)}%")

    def reset(self) -> None:
        self.clear_log()
        self.set_progress(0, 1)
```

- [ ] **Step 2: Smoke-test that it imports and paints**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
from PyQt6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv)
from wizard_widgets import Card, RunConsole
c = Card("Chapters", "11 / 11 selected"); c.set_meta("3 / 11 selected")
rc = RunConsole()
rc.append("Chapter 3.1/4  rewriting…", "info")
rc.append("✓ saved chapter 19", "success")
rc.append("✗ failed", "error")
rc.append("unknown-level line", "bogus")     # must not raise
rc.set_progress(47, 100)
print("Card + RunConsole OK")
EOF
```
Expected: `Card + RunConsole OK`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_widgets.py
git add wizard_widgets.py
git commit -m "feat(wizard): Card + RunConsole widgets"
```

---

## Task 8: `WizardSlider` — the signature interaction

**Files:**
- Modify: `wizard_widgets.py`

**Interfaces:**
- Consumes: `wizard_logic.keep_pct_readout`, `creativity_notch`, `creativity_readout`, `is_creativity_sweet`; `wizard_theme.RAMP`.
- Produces: `WizardSlider(QWidget)` with:
  - `WizardSlider.keep_pct(parent=None) -> WizardSlider` (10–90, step 10, default 40)
  - `WizardSlider.creativity(parent=None) -> WizardSlider` (1–10, step 1, default 5)
  - signal `valueChanged(int)`; methods `value() -> int`, `set_value(int)`

Design: 6px track radius 99, tick marks, 17px amber knob with a 2px `#15150f` ring, fill gradient `#5b594f` → current ramp colour, `✦ sweet spot` pill. An invisible native `QSlider` overlays the paint area for mouse + keyboard.

- [ ] **Step 1: Append `WizardSlider` to `wizard_widgets.py`**

Add `QSlider` to the `QtWidgets` import list at the top of the file.

```python
class WizardSlider(QWidget):
    """Custom-painted slider with a live readout and sweet-spot pill.

    Two flavours, built via the classmethods. The kind determines the range,
    the snap, the readout text, and where the sweet spot lies — all of which
    come from wizard_logic, never from this file.
    """

    valueChanged = pyqtSignal(int)

    _TRACK_H = 6
    _KNOB_R = 8            # 17px diameter, minus the 1px ring allowance
    _ROW_H = 26

    def __init__(self, kind: str, lo: int, hi: int, step: int, default: int,
                 legend: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind          # "keep" | "creativity"
        self._lo, self._hi, self._step = lo, hi, step

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._track_area = QWidget()
        self._track_area.setFixedHeight(self._ROW_H)
        layout.addWidget(self._track_area)

        # Invisible native slider laid over the painted track: it owns
        # interaction (drag, click, arrow keys, page-up/down) so we do not
        # reimplement hit-testing.
        self._slider = QSlider(Qt.Orientation.Horizontal, self._track_area)
        self._slider.setRange(lo, hi)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setValue(default)
        self._slider.setStyleSheet("background: transparent;")
        self._slider.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self._slider.lower()
        self._slider.valueChanged.connect(self._on_change)

        readout_row = QHBoxLayout()
        readout_row.setSpacing(9)
        self._readout = QLabel()
        readout_row.addWidget(self._readout)
        readout_row.addStretch()
        self._pill = QLabel("✦ sweet spot")
        self._pill.setStyleSheet(
            f"color:{RAMP['green']}; background:{W_TILE_SELECTED};"
            f"border-radius:9px; padding:2px 9px; font-size:10px;"
        )
        readout_row.addWidget(self._pill)
        layout.addLayout(readout_row)

        ends = QHBoxLayout()
        lo_lbl, hi_lbl = QLabel(self._end_label(lo)), QLabel(self._end_label(hi))
        for lbl in (lo_lbl, hi_lbl):
            lbl.setStyleSheet(f"color:{W_FAINT2}; font-size:10px;")
        ends.addWidget(lo_lbl)
        ends.addStretch()
        ends.addWidget(hi_lbl)
        layout.addLayout(ends)

        legend_lbl = QLabel(legend)
        legend_lbl.setObjectName("helper")
        layout.addWidget(legend_lbl)

        self._track_area.paintEvent = self._paint_track   # type: ignore[method-assign]
        self._on_change(default)

    # ── constructors ──
    @classmethod
    def keep_pct(cls, parent: QWidget | None = None) -> "WizardSlider":
        return cls(
            "keep", 10, 90, 10, 40,
            "🟢  30–50% keeps the core story without noise", parent,
        )

    @classmethod
    def creativity(cls, parent: QWidget | None = None) -> "WizardSlider":
        return cls(
            "creativity", 1, 10, 1, 5,
            "🟢  5–6 adds vivid prose without inventing plot", parent,
        )

    # ── value ──
    def value(self) -> int:
        return self._slider.value()

    def set_value(self, v: int) -> None:
        self._slider.setValue(v)

    def resizeEvent(self, event) -> None:              # noqa: N802
        super().resizeEvent(event)
        self._slider.setGeometry(self._track_area.rect())

    # ── presentation, all sourced from wizard_logic ──
    def _end_label(self, v: int) -> str:
        if self._kind == "keep":
            return f"{v}%"
        return f"{v} · {wl.creativity_notch(v)[0]}"

    def _readout_for(self, v: int) -> tuple[str, str, bool]:
        """(text, hex colour, is_sweet). Ramp keys become hexes only here."""
        if self._kind == "keep":
            text, sweet = wl.keep_pct_readout(v)
            colour = RAMP["green"] if sweet else W_MUTED
            return text, colour, sweet
        sweet = wl.is_creativity_sweet(v)
        _, ramp_key = wl.creativity_notch(v)
        return wl.creativity_readout(v), RAMP[ramp_key], sweet

    def _on_change(self, v: int) -> None:
        text, colour, sweet = self._readout_for(v)
        self._readout.setText(text)
        self._readout.setStyleSheet(
            f"color:{colour}; font-size:12px; font-weight:600;"
        )
        self._pill.setVisible(sweet)
        self._current_colour = colour
        self._track_area.update()
        self.valueChanged.emit(v)

    def _paint_track(self, _event) -> None:
        p = QPainter(self._track_area)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._track_area.rect()
        cy = r.center().y()
        x0, x1 = r.left() + self._KNOB_R, r.right() - self._KNOB_R
        span = max(1, x1 - x0)
        frac = (self.value() - self._lo) / max(1, self._hi - self._lo)
        knob_x = x0 + int(span * frac)

        # track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(W_TRACK))
        p.drawRoundedRect(x0, cy - self._TRACK_H // 2, span, self._TRACK_H, 3, 3)

        # ticks
        p.setPen(QPen(QColor(W_FAINT2), 1))
        n_ticks = (self._hi - self._lo) // self._step
        for i in range(n_ticks + 1):
            tx = x0 + int(span * i / n_ticks)
            p.drawLine(tx, cy + 5, tx, cy + 8)

        # fill: #5b594f → the current ramp colour
        if knob_x > x0:
            grad = QLinearGradient(x0, 0, knob_x, 0)
            grad.setColorAt(0.0, QColor(W_FILL_START))
            grad.setColorAt(1.0, QColor(self._current_colour))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(
                x0, cy - self._TRACK_H // 2, knob_x - x0, self._TRACK_H, 3, 3
            )

        # knob: amber disc with a dark ring
        p.setPen(QPen(QColor(W_KNOB_RING), 2))
        p.setBrush(QColor(self._current_colour))
        p.drawEllipse(knob_x - self._KNOB_R, cy - self._KNOB_R,
                      self._KNOB_R * 2, self._KNOB_R * 2)
```

- [ ] **Step 2: Smoke-test both flavours across their full range**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from wizard_widgets import WizardSlider
k = WizardSlider.keep_pct()
assert k.value() == 40
for v in range(10, 91, 10):
    k.set_value(v)
c = WizardSlider.creativity()
assert c.value() == 5
for v in range(1, 11):
    c.set_value(v)
c.set_value(5)
print("sliders OK — creativity readout:", c._readout.text())
EOF
```
Expected: `sliders OK — creativity readout: Enriched+ — level 5/10  (temp ≈ 0.68)`

Note the `0.68`, not the mockup's `0.44`. If you see `0.44`, `wizard_logic.creativity_readout` is duplicating the formula instead of calling `settings.creativity_to_temperature`.

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_widgets.py
git add wizard_widgets.py
git commit -m "feat(wizard): custom-painted WizardSlider with sweet-spot pill"
```

---

## Task 9: `StepRail`, `ModeTileGrid`, `TriStateChapterList`

**Files:**
- Modify: `wizard_widgets.py`

**Interfaces:**
- Consumes: `wizard_theme.W_*`.
- Produces:
  - `StepRail(QWidget)`: signal `stepClicked(int)`; `set_state(current: int, completed: set[int], errors: set[int])`
  - `ModeTileGrid(QWidget)`: signal `modeChanged(str)`; `set_mode(str)`, `mode() -> str`. Tiles in `wizard_logic.MODES` order.
  - `TriStateChapterList(QWidget)`: signal `selectionChanged()`; `set_chapters(rows: list[ChapterRow])`, `rows() -> list[ChapterRow]`, `clear()`

- [ ] **Step 1: Append the three widgets to `wizard_widgets.py`**

Add `QButtonGroup, QCheckBox, QRadioButton, QScrollArea, QGridLayout` to the `QtWidgets` import list.

```python
_STEP_LABELS = ("Book", "Transform", "Output", "Run")


class StepRail(QWidget):
    """Four numbered badges joined by connector lines. The whole step is clickable."""

    stepClicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        self._badges: list[QLabel] = []
        self._labels: list[QLabel] = []
        for i, name in enumerate(_STEP_LABELS, start=1):
            badge = QLabel(str(i))
            badge.setFixedSize(23, 23)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.mousePressEvent = self._clicker(i)      # type: ignore[method-assign]
            label = QLabel(name)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.mousePressEvent = self._clicker(i)      # type: ignore[method-assign]
            self._badges.append(badge)
            self._labels.append(label)
            row.addWidget(badge)
            row.addWidget(label)
            if i < len(_STEP_LABELS):
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet(f"color:{W_BORDER};")
                row.addWidget(line, 1)
        self.set_state(1, set(), set())

    def _clicker(self, step: int):
        def handler(_event):
            self.stepClicked.emit(step)
        return handler

    def set_state(self, current: int, completed: set[int],
                  errors: set[int]) -> None:
        for i, (badge, label) in enumerate(zip(self._badges, self._labels), 1):
            if i in errors:
                badge.setText("!")
                badge.setStyleSheet(
                    f"border:1px solid {W_ERROR}; border-radius:11px;"
                    f"color:{W_ERROR}; font-size:11px; font-weight:700;"
                )
                label.setStyleSheet(f"color:{W_ERROR}; font-size:12px;")
            elif i == current:
                badge.setText(str(i))
                badge.setStyleSheet(
                    f"background:{W_AMBER}; border-radius:11px;"
                    f"color:{W_KNOB_RING}; font-size:11px; font-weight:700;"
                )
                label.setStyleSheet(f"color:{W_AMBER}; font-size:12px; font-weight:600;")
            elif i in completed:
                badge.setText("✓")
                badge.setStyleSheet(
                    f"background:{W_BADGE_DONE_BG}; border-radius:11px;"
                    f"color:{W_TEXT_SECONDARY}; font-size:11px;"
                )
                label.setStyleSheet(f"color:{W_TEXT_SECONDARY}; font-size:12px;")
            else:
                badge.setText(str(i))
                badge.setStyleSheet(
                    f"border:1px solid {W_BORDER_CTRL}; border-radius:11px;"
                    f"color:{W_MUTED}; font-size:11px;"
                )
                label.setStyleSheet(f"color:{W_MUTED}; font-size:12px;")


_MODE_TILES = (
    ("sr",   "Summarise → rewrite", "condense, then retell in Spanish at your level"),
    ("full", "Full translation",    "whole text, nothing cut — slower"),
    ("sum",  "Summarise only (EN)", "condensed English, no translation"),
    ("key",  "Summary + key ideas", "+ a book-wide synthesis at the end"),
)


class ModeTileGrid(QWidget):
    """2×2 grid of radio tiles. Selected tile: amber border + tinted fill."""

    modeChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        self._group = QButtonGroup(self)
        self._tiles: dict[str, QFrame] = {}
        self._radios: dict[str, QRadioButton] = {}

        for i, (key, title, desc) in enumerate(_MODE_TILES):
            tile = QFrame()
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            box = QVBoxLayout(tile)
            box.setContentsMargins(12, 11, 12, 11)
            box.setSpacing(3)
            radio = QRadioButton(title)
            radio.setStyleSheet("font-size:13px; font-weight:600;")
            self._group.addButton(radio)
            box.addWidget(radio)
            sub = QLabel(desc)
            sub.setObjectName("helper")
            sub.setContentsMargins(25, 0, 0, 0)
            box.addWidget(sub)
            grid.addWidget(tile, i // 2, i % 2)
            self._tiles[key] = tile
            self._radios[key] = radio
            radio.toggled.connect(
                lambda checked, k=key: checked and self._select(k)
            )
            tile.mousePressEvent = self._clicker(key)     # type: ignore[method-assign]

        self._mode = "sr"
        self._radios["sr"].setChecked(True)
        self._restyle()

    def _clicker(self, key: str):
        def handler(_event):
            self._radios[key].setChecked(True)
        return handler

    def _select(self, key: str) -> None:
        if key == self._mode:
            return
        self._mode = key
        self._restyle()
        self.modeChanged.emit(key)

    def _restyle(self) -> None:
        for key, tile in self._tiles.items():
            if key == self._mode:
                tile.setStyleSheet(
                    f"background:{W_TILE_SELECTED}; border:1px solid {W_AMBER};"
                    f"border-radius:9px;"
                )
            else:
                tile.setStyleSheet(
                    f"background:{W_SURFACE}; border:1px solid {W_BORDER};"
                    f"border-radius:9px;"
                )

    def mode(self) -> str:
        return self._mode

    def set_mode(self, key: str) -> None:
        self._radios[key].setChecked(True)


class TriStateChapterList(QWidget):
    """'Select all' tri-state master + a scrollable list of chapter checkboxes."""

    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._master = QCheckBox("Select all")
        self._master.setTristate(True)
        self._master.clicked.connect(self._on_master_clicked)
        layout.addWidget(self._master)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 6, 8, 6)
        self._inner_layout.setSpacing(2)
        self._inner_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._inner)
        scroll.setMaximumHeight(188)
        scroll.setStyleSheet(
            f"background:{W_INSET}; border:1px solid {W_BORDER};"
            f"border-radius:8px;"
        )
        layout.addWidget(scroll)

        self._boxes: list[tuple[int, QCheckBox]] = []

    def clear(self) -> None:
        for _, box in self._boxes:
            box.setParent(None)
        self._boxes = []
        self._sync_master()

    def set_chapters(self, rows: list["wl.ChapterRow"]) -> None:
        self.clear()
        for row in rows:
            box = QCheckBox(f"{row.index + 1:02d}.  {row.title}")
            box.setChecked(row.checked)
            box.setStyleSheet(f"QCheckBox:hover {{ background:{W_ROW_HOVER}; }}")
            box.stateChanged.connect(self._on_child_changed)
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, box)
            self._boxes.append((row.index, box))
        self._sync_master()

    def rows(self) -> list["wl.ChapterRow"]:
        return [
            wl.ChapterRow(idx, box.text().split(".", 1)[1].strip(), box.isChecked())
            for idx, box in self._boxes
        ]

    def _on_master_clicked(self) -> None:
        # A tri-state master must drive children to a definite state, never
        # leave them Partially — clicking it always means "all" or "none".
        target = self._master.checkState() != Qt.CheckState.Unchecked
        for _, box in self._boxes:
            box.blockSignals(True)
            box.setChecked(target)
            box.blockSignals(False)
        self._sync_master()
        self.selectionChanged.emit()

    def _on_child_changed(self, _state: int) -> None:
        self._sync_master()
        self.selectionChanged.emit()

    def _sync_master(self) -> None:
        total = len(self._boxes)
        checked = sum(1 for _, box in self._boxes if box.isChecked())
        self._master.blockSignals(True)
        if total and checked == total:
            self._master.setCheckState(Qt.CheckState.Checked)
        elif checked == 0:
            self._master.setCheckState(Qt.CheckState.Unchecked)
        else:
            self._master.setCheckState(Qt.CheckState.PartiallyChecked)
        self._master.blockSignals(False)
```

- [ ] **Step 2: Smoke-test tri-state round-tripping**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from wizard_widgets import StepRail, ModeTileGrid, TriStateChapterList

lst = TriStateChapterList()
rows = [wl.ChapterRow(i, f"Chapter {i+1}") for i in range(5)]
lst.set_chapters(rows)
assert lst._master.checkState() == Qt.CheckState.Checked
assert [r.index for r in lst.rows()] == [0,1,2,3,4]
assert all(r.checked for r in lst.rows())

lst._boxes[0][1].setChecked(False)
assert lst._master.checkState() == Qt.CheckState.PartiallyChecked
assert [r.index for r in lst.rows() if r.checked] == [1,2,3,4]
# titles must survive the "NN.  Title" round-trip
assert lst.rows()[3].title == "Chapter 4"

grid = ModeTileGrid()
assert grid.mode() == "sr"
grid.set_mode("key"); assert grid.mode() == "key"

rail = StepRail()
rail.set_state(2, {1}, {3})
print("StepRail + ModeTileGrid + TriStateChapterList OK")
EOF
```
Expected: `StepRail + ModeTileGrid + TriStateChapterList OK`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_widgets.py
git add wizard_widgets.py
git commit -m "feat(wizard): StepRail, ModeTileGrid, TriStateChapterList"
```

---

## Task 10: `StepBook`

**Files:**
- Create: `wizard_steps.py`

**Interfaces:**
- Consumes: `Card`, `TriStateChapterList`; `settings.SETTINGS`; `epub_io` (lazy).
- Produces: `StepBook(QWidget)`; signal `changed()`; `apply_to(state: WizardState)`, `load_from(state: WizardState)`.

> `epub_io` is imported lazily inside the file-selected handler, matching `app.py:_on_epub_selected`. `SETTINGS` is read here (not in `wizard_logic`) because the model list is UI data.

- [ ] **Step 1: Create `wizard_steps.py` with `StepBook`**

```python
"""
wizard_steps.py
---------------
One QWidget per wizard step. Each step owns its controls, writes into the
shared WizardState via apply_to(), and re-reads it via load_from().

Imports wizard_widgets, wizard_theme, wizard_logic and settings. Never
imports app.py or widgets.py (the old UI). epub_io is imported lazily.
"""

import importlib.util
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

import wizard_logic as wl
from settings import SETTINGS
from wizard_widgets import Card, TriStateChapterList


def _prompt(text: str, caveat_family: str | None) -> QLabel:
    """The decorative hand-lettered per-step prompt.

    Falls back to muted italic system text when Caveat is unavailable — the
    prompt is cosmetic and must never be a startup dependency.
    """
    lbl = QLabel(text)
    lbl.setObjectName("stepPrompt")
    if caveat_family:
        font = lbl.font()
        font.setFamily(caveat_family)
        font.setPointSize(16)
        lbl.setFont(font)
    else:
        font = lbl.font()
        font.setItalic(True)
        lbl.setFont(font)
    return lbl


class StepBook(QWidget):
    """Step 1 — identify the book and choose what to process."""

    changed = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chapters: list[wl.ChapterRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("which book are we weaving?", caveat))

        # ── EPUB file ──
        file_card = Card("EPUB file")
        row = QHBoxLayout()
        row.setSpacing(8)
        self._path = QLineEdit()
        self._path.setReadOnly(True)
        self._path.setPlaceholderText("No file selected")
        row.addWidget(self._path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        file_card.body.addLayout(row)
        helper = QLabel(
            "Selecting a file reads title, author & chapters, "
            "and pre-fills the output folder."
        )
        helper.setObjectName("helper")
        file_card.body.addWidget(helper)
        layout.addWidget(file_card)

        # ── Chapters ──
        self._chapters_card = Card("Chapters", "0 / 0 selected")
        self._list = TriStateChapterList()
        self._list.selectionChanged.connect(self._on_selection_changed)
        self._chapters_card.body.addWidget(self._list)
        layout.addWidget(self._chapters_card)

        # ── Model ──
        backend = SETTINGS.get("llm_backend", "ollama")
        model_card = Card(f"Model ({backend})")
        self._model = QComboBox()
        for entry in SETTINGS["models"]:
            self._model.addItem(entry["label"], userData=entry["value"])
        default = SETTINGS["default_model"]
        idx = self._model.findData(default)
        if idx >= 0:
            self._model.setCurrentIndex(idx)
        self._model.currentIndexChanged.connect(lambda _i: self.changed.emit())
        model_card.body.addWidget(self._model)
        layout.addWidget(model_card)
        layout.addStretch()

    # ── public API ──
    def model_label(self) -> str:
        return self._model.currentText()

    def apply_to(self, state: wl.WizardState) -> None:
        state.epub_path = self._path.text()
        state.chapters = self._list.rows()
        state.model = self._model.currentData()

    def load_from(self, state: wl.WizardState) -> None:
        self._path.setText(state.epub_path)
        if state.chapters:
            self._list.set_chapters(state.chapters)
        self._refresh_meta()

    def set_enabled_controls(self, enabled: bool) -> None:
        for w in (self._path, self._list, self._model):
            w.setEnabled(enabled)

    # ── internals ──
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an EPUB", str(Path.home()), "EPUB files (*.epub)"
        )
        if path:
            self._load_epub(path)

    def _load_epub(self, path: str) -> None:
        self._path.setText(path)
        # Lazy, exactly as app.py:_on_epub_selected does.
        try:
            import epub_io
            preview = SETTINGS.get("chapter_title_preview_chars", 50)
            chapters = epub_io.extract_chapters(path, preview)
            self._chapters = [
                wl.ChapterRow(c.index, c.title, True) for c in chapters
            ]
            self._list.set_chapters(self._chapters)
        except Exception:
            self._chapters = []
            self._list.clear()
        self._refresh_meta()
        self.changed.emit()

    def read_book_metadata(self, path: str) -> tuple[str, str]:
        """(title, author) from the EPUB's DC metadata; ('', '') on failure."""
        try:
            from ebooklib import epub as ebooklib_epub
            book = ebooklib_epub.read_epub(path)
            title = book.get_metadata("DC", "title")
            author = book.get_metadata("DC", "creator")
            return (title[0][0] if title else "",
                    author[0][0] if author else "")
        except Exception:
            return "", ""

    def _on_selection_changed(self) -> None:
        self._refresh_meta()
        self.changed.emit()

    def _refresh_meta(self) -> None:
        rows = self._list.rows()
        total = len(rows)
        selected = sum(1 for r in rows if r.checked)
        self._chapters_card.set_meta(f"{selected} / {total} selected")
```

- [ ] **Step 2: Smoke-test**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from wizard_steps import StepBook
s = StepBook()
st = wl.WizardState()
s.apply_to(st)
assert st.model, "model must be seeded from SETTINGS['default_model']"
assert st.epub_path == ""
print("StepBook OK, default model:", st.model)
EOF
```
Expected: `StepBook OK, default model: mlx-community/gemma-4-31B-it-qat-8bit`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_steps.py
git add wizard_steps.py
git commit -m "feat(wizard): StepBook"
```

---

## Task 11: `StepTransform` with animated reveals

**Files:**
- Modify: `wizard_steps.py`

**Interfaces:**
- Consumes: `Card`, `WizardSlider`, `ModeTileGrid`; `wl.derive_target_is_spanish`.
- Produces: `StepTransform(QWidget)`; signals `changed()`, `modeChanged(str)`, `languageChanged()`; `apply_to`, `load_from`, `set_enabled_controls`. Also `_reveal(widget, visible)` helper animating `maximumHeight` + opacity over 180 ms `OutCubic`.

> `languageChanged` is what makes Step 3 re-populate its voice list. It fires when the mode changes *or* the key-ideas language tile flips — both can move `derive_target_is_spanish`.

- [ ] **Step 1: Append `_Reveal` + `StepTransform` to `wizard_steps.py`**

Extend the imports:

```python
from PyQt6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, pyqtSignal,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QRadioButton, QButtonGroup
from wizard_widgets import Card, ModeTileGrid, TriStateChapterList, WizardSlider
```

```python
_REVEAL_MS = 180


class _Reveal:
    """Animates a widget's maximumHeight + opacity. 'Don't pop.'

    Qt has no built-in collapse. We drive maximumHeight from 0 to the
    widget's sizeHint and back, pairing it with an opacity effect so the
    content fades rather than sliding out of a clipping rect.
    """

    def __init__(self, widget: QWidget) -> None:
        self._w = widget
        self._effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(self._effect)
        self._effect.setOpacity(1.0)
        self._group: QParallelAnimationGroup | None = None
        self._visible = True

    def set_visible(self, visible: bool, animate: bool = True) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        target_h = self._w.sizeHint().height() if visible else 0
        if not animate:
            self._w.setVisible(visible)
            self._w.setMaximumHeight(target_h if visible else 0)
            self._effect.setOpacity(1.0 if visible else 0.0)
            return
        if visible:
            self._w.setVisible(True)

        group = QParallelAnimationGroup(self._w)
        h_anim = QPropertyAnimation(self._w, b"maximumHeight")
        h_anim.setDuration(_REVEAL_MS)
        h_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        h_anim.setStartValue(self._w.height())
        h_anim.setEndValue(target_h)
        group.addAnimation(h_anim)

        o_anim = QPropertyAnimation(self._effect, b"opacity")
        o_anim.setDuration(_REVEAL_MS)
        o_anim.setStartValue(self._effect.opacity())
        o_anim.setEndValue(1.0 if visible else 0.0)
        group.addAnimation(o_anim)

        if not visible:
            group.finished.connect(lambda: self._w.setVisible(False))
        else:
            # Release the cap so the card can grow with its content later.
            group.finished.connect(lambda: self._w.setMaximumHeight(16777215))
        self._group = group
        group.start()


_LEVELS = (
    ("B1 — Threshold", "B1"), ("B2 — Vantage", "B2"),
    ("C1 — Advanced", "C1"), ("C2 — Mastery", "C2"),
)
_CARRY = (
    ("Off — no continuity aid", "off"),
    ("Names only — protect proper nouns", "names"),
    ("Prose tail — scene-gated carry-over", "tail"),
    ("Both — names + prose tail", "both"),
)
_CARRY_NOTES = {
    "off":   "No continuity aid — each chunk is processed independently.",
    "names": "Character and place names from each chunk's source are passed "
             "to the model so spellings stay consistent. No extra model calls.",
    "tail":  "The last ~120 words of the previous chunk's output carry into "
             "the next prompt; the carry resets at scene breaks and chapter "
             "starts. Also hard-splits chapters at scene breaks, which can "
             "add model calls.",
    "both":  "Both mechanisms together; highest continuity, may add model "
             "calls at scene breaks.",
}


class StepTransform(QWidget):
    """Step 2 — the mode tiles, the two sliders, and the mode-driven reveals."""

    changed = pyqtSignal()
    modeChanged = pyqtSignal(str)
    languageChanged = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("how should we transform it?", caveat))

        self._tiles = ModeTileGrid()
        self._tiles.modeChanged.connect(self._on_mode_changed)
        layout.addWidget(self._tiles)

        # ── the two sliders, side by side ──
        slider_row = QHBoxLayout()
        slider_row.setSpacing(13)
        self._depth_card = Card("Summarisation depth")
        self._keep = WizardSlider.keep_pct()
        self._keep.valueChanged.connect(lambda _v: self.changed.emit())
        self._depth_card.body.addWidget(self._keep)
        slider_row.addWidget(self._depth_card, 1)

        creativity_card = Card("Creativity")
        self._creativity = WizardSlider.creativity()
        self._creativity.valueChanged.connect(lambda _v: self.changed.emit())
        creativity_card.body.addWidget(self._creativity)
        slider_row.addWidget(creativity_card, 1)
        layout.addLayout(slider_row)

        # ── mode-conditional notes ──
        self._translate_note = self._note(
            "⚠️  Full text is translated directly — expect longer model calls. "
            "Consider raising the timeout in step 3."
        )
        self._sum_note = self._note(
            "ℹ️  Output stays in English; no translation is performed."
        )
        layout.addWidget(self._translate_note)
        layout.addWidget(self._sum_note)

        # ── key-ideas language ──
        self._key_card = Card("Key-ideas output language")
        key_row = QHBoxLayout()
        self._key_group = QButtonGroup(self)
        self._key_es = QRadioButton("Spanish (at your CEFR level)")
        self._key_en = QRadioButton("English")
        self._key_es.setChecked(True)
        for btn in (self._key_es, self._key_en):
            self._key_group.addButton(btn)
            key_row.addWidget(btn)
            btn.toggled.connect(self._on_key_lang_changed)
        self._key_card.body.addLayout(key_row)
        key_note = QLabel("Changing this re-populates the MP3 voice list in step 3.")
        key_note.setObjectName("helper")
        self._key_card.body.addWidget(key_note)
        layout.addWidget(self._key_card)

        # ── Spanish level (gated on target_is_spanish) ──
        self._level_card = Card("Spanish level")
        self._level = QComboBox()
        for label, value in _LEVELS:
            self._level.addItem(label, userData=value)
        self._level.setCurrentIndex(1)                 # B2
        self._level.setMaximumWidth(280)
        self._level.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self._level_card.body.addWidget(self._level)
        level_help = QLabel("Target CEFR level for the rewritten Spanish.")
        level_help.setObjectName("helper")
        self._level_card.body.addWidget(level_help)
        layout.addWidget(self._level_card)

        # ── continuity (never gated) ──
        carry_card = Card("Cross-chunk continuity")
        self._carry = QComboBox()
        for label, value in _CARRY:
            self._carry.addItem(label, userData=value)
        self._carry.setMaximumWidth(340)
        self._carry.currentIndexChanged.connect(self._on_carry_changed)
        carry_card.body.addWidget(self._carry)
        self._carry_note = QLabel(_CARRY_NOTES["off"])
        self._carry_note.setObjectName("helper")
        self._carry_note.setWordWrap(True)
        carry_card.body.addWidget(self._carry_note)
        layout.addWidget(carry_card)
        layout.addStretch()

        self._reveals = {
            "depth":     _Reveal(self._depth_card),
            "translate": _Reveal(self._translate_note),
            "sum":       _Reveal(self._sum_note),
            "key":       _Reveal(self._key_card),
            "level":     _Reveal(self._level_card),
        }
        self._sync_reveals(animate=False)

    def _note(self, text: str) -> QWidget:
        frame = Card("")
        frame.setObjectName("note")
        lbl = QLabel(text)
        lbl.setObjectName("helper")
        lbl.setWordWrap(True)
        frame.body.addWidget(lbl)
        return frame

    # ── public API ──
    def apply_to(self, state: wl.WizardState) -> None:
        state.mode = self._tiles.mode()
        state.key_ideas_lang = "en" if self._key_en.isChecked() else "es"
        state.cefr_level = self._level.currentData()
        state.carry = self._carry.currentData()
        state.keep_pct = self._keep.value()
        state.creativity = self._creativity.value()

    def load_from(self, state: wl.WizardState) -> None:
        self._tiles.set_mode(state.mode)
        self._keep.set_value(state.keep_pct)
        self._creativity.set_value(state.creativity)

    def set_enabled_controls(self, enabled: bool) -> None:
        for w in (self._tiles, self._keep, self._creativity,
                  self._level, self._carry, self._key_es, self._key_en):
            w.setEnabled(enabled)

    # ── internals ──
    def _on_mode_changed(self, mode: str) -> None:
        self._sync_reveals()
        self.modeChanged.emit(mode)
        self.languageChanged.emit()      # mode can flip target_is_spanish
        self.changed.emit()

    def _on_key_lang_changed(self, checked: bool) -> None:
        if not checked:
            return                        # ignore the untoggled partner
        self._sync_reveals()
        self.languageChanged.emit()
        self.changed.emit()

    def _on_carry_changed(self, _i: int) -> None:
        self._carry_note.setText(_CARRY_NOTES[self._carry.currentData()])
        self.changed.emit()

    def _sync_reveals(self, animate: bool = True) -> None:
        mode = self._tiles.mode()
        key_lang = "en" if self._key_en.isChecked() else "es"
        self._reveals["depth"].set_visible(mode != "full", animate)
        self._reveals["translate"].set_visible(mode == "full", animate)
        self._reveals["sum"].set_visible(mode == "sum", animate)
        self._reveals["key"].set_visible(mode == "key", animate)
        self._reveals["level"].set_visible(
            wl.derive_target_is_spanish(mode, key_lang), animate
        )
```

- [ ] **Step 2: Smoke-test every reveal combination**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from wizard_steps import StepTransform
s = StepTransform()
for mode in wl.MODES:
    s._tiles.set_mode(mode)
    app.processEvents()
st = wl.WizardState(); s._tiles.set_mode("key"); s._key_en.setChecked(True)
s.apply_to(st)
assert st.mode == "key" and st.key_ideas_lang == "en"
assert wl.derive_target_is_spanish(st.mode, st.key_ideas_lang) is False
s._key_es.setChecked(True); s.apply_to(st)
assert wl.derive_target_is_spanish(st.mode, st.key_ideas_lang) is True
s._carry.setCurrentIndex(2); s.apply_to(st)
assert st.carry == "tail"
assert wl.build_config(
    wl.WizardState(epub_path="/a/b.epub", carry="tail"), "mlx"
)["carry_mode"] == "prose"
print("StepTransform OK")
EOF
```
Expected: `StepTransform OK`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_steps.py
git add wizard_steps.py
git commit -m "feat(wizard): StepTransform with animated mode-driven reveals"
```

---

## Task 12: `StepOutput` — formats, MP3, metadata, backend-aware stepper

**Files:**
- Modify: `wizard_steps.py`

**Interfaces:**
- Consumes: `Card`; `settings.SETTINGS`, `settings.OLLAMA_TIMEOUT`, `settings.voices_for_language`.
- Produces: `StepOutput(QWidget)`; signal `changed()`; `apply_to`, `load_from`, `set_enabled_controls`, `repopulate_voices(target_is_spanish: bool)`, `timeout_value() -> int`, `max_tokens_value() -> int`.

Backend-aware Step-3 stepper, per the spec: on `mlx` show **Max tokens per call**; on `ollama` show **Timeout per call**. Only one is built.

MP3 gating (mirrors `app.py:655-672`): disabled when Kokoro is absent **or** `.txt` is unchecked.

- [ ] **Step 1: Append `StepOutput` to `wizard_steps.py`**

Extend imports: `from PyQt6.QtWidgets import QCheckBox, QGridLayout, QSpinBox`
and `from settings import SETTINGS, OLLAMA_TIMEOUT, voices_for_language`.

```python
_KOKORO_AVAILABLE = importlib.util.find_spec("kokoro") is not None


class StepOutput(QWidget):
    """Step 3 — formats, audio, destination, metadata, advanced."""

    changed = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = SETTINGS.get("llm_backend", "ollama")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("where should it land?", caveat))

        # ── formats ──
        fmt_card = Card("Output formats", "at least one")
        fmt_row = QHBoxLayout()
        self._fmt = {
            "txt":  QCheckBox("Plain text (.txt)"),
            "epub": QCheckBox("EPUB (.epub)"),
            "html": QCheckBox("HTML (.html)"),
        }
        self._fmt["txt"].setChecked(True)
        for box in self._fmt.values():
            box.stateChanged.connect(self._on_formats_changed)
            fmt_row.addWidget(box)
        fmt_row.addStretch()
        fmt_card.body.addLayout(fmt_row)

        self._mp3 = QCheckBox("Generate MP3 audiobook (Kokoro TTS)")
        self._mp3.stateChanged.connect(self._on_mp3_toggled)
        fmt_card.body.addWidget(self._mp3)
        self._mp3_note = QLabel("")
        self._mp3_note.setObjectName("helper")
        fmt_card.body.addWidget(self._mp3_note)

        self._voice_wrap = QWidget()
        voice_box = QHBoxLayout(self._voice_wrap)
        voice_box.setContentsMargins(26, 0, 0, 0)
        voice_box.addWidget(QLabel("Voice:"))
        self._voice = QComboBox()
        self._voice.currentIndexChanged.connect(lambda _i: self.changed.emit())
        voice_box.addWidget(self._voice, 1)
        fmt_card.body.addWidget(self._voice_wrap)
        layout.addWidget(fmt_card)

        # ── output folder ──
        folder_card = Card("Output folder")
        folder_row = QHBoxLayout()
        self._folder = QLineEdit()
        self._folder.textChanged.connect(lambda _t: self.changed.emit())
        folder_row.addWidget(self._folder, 1)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._browse_folder)
        folder_row.addWidget(pick)
        folder_card.body.addLayout(folder_row)
        layout.addWidget(folder_card)

        # ── EPUB metadata (gated on .epub) ──
        self._meta_card = Card("EPUB metadata")
        grid = QGridLayout()
        grid.setSpacing(9)
        self._meta_title = QLineEdit()
        self._meta_creator = QLineEdit()
        self._meta_language = QLineEdit("es")
        self._meta_contributor = QLineEdit()
        for col, (label, widget) in enumerate([
            ("Title", self._meta_title), ("Author", self._meta_creator),
        ]):
            grid.addWidget(QLabel(label), 0, col * 2)
            grid.addWidget(widget, 0, col * 2 + 1)
        for col, (label, widget) in enumerate([
            ("Language", self._meta_language),
            ("Contributor", self._meta_contributor),
        ]):
            grid.addWidget(QLabel(label), 1, col * 2)
            grid.addWidget(widget, 1, col * 2 + 1)
        for widget in (self._meta_title, self._meta_creator,
                       self._meta_language, self._meta_contributor):
            widget.textChanged.connect(lambda _t: self.changed.emit())
        self._meta_card.body.addLayout(grid)
        layout.addWidget(self._meta_card)

        # ── advanced: backend-aware stepper + chunk size ──
        adv_row = QHBoxLayout()
        adv_row.setSpacing(13)
        self._timeout: QSpinBox | None = None
        self._tokens: QSpinBox | None = None

        if self._backend == "mlx":
            tok_card = Card("Max tokens per call")
            self._tokens = QSpinBox()
            self._tokens.setRange(256, 65536)
            self._tokens.setSingleStep(256)
            self._tokens.setValue(SETTINGS.get("mlx_max_tokens", 8192))
            self._tokens.setSuffix("  tokens")
            self._tokens.valueChanged.connect(lambda _v: self.changed.emit())
            tok_card.body.addWidget(self._tokens)
            hint = QLabel("caps runaway output — mlx cannot abort mid-call")
            hint.setObjectName("helper")
            tok_card.body.addWidget(hint)
            adv_row.addWidget(tok_card, 1)
        else:
            to_card = Card("Timeout per call")
            self._timeout = QSpinBox()
            self._timeout.setRange(30, 3600)
            self._timeout.setSingleStep(30)
            self._timeout.setValue(OLLAMA_TIMEOUT)
            self._timeout.setSuffix("  s")
            self._timeout.valueChanged.connect(lambda _v: self.changed.emit())
            to_card.body.addWidget(self._timeout)
            hint = QLabel("raise for Full translation")
            hint.setObjectName("helper")
            to_card.body.addWidget(hint)
            adv_row.addWidget(to_card, 1)

        chunk_card = Card("Chunk size")
        self._chunk = QSpinBox()
        self._chunk.setRange(200, 10000)
        self._chunk.setSingleStep(100)
        self._chunk.setValue(2000)
        self._chunk.setSuffix("  words")
        self._chunk.valueChanged.connect(lambda _v: self.changed.emit())
        chunk_card.body.addWidget(self._chunk)
        chunk_hint = QLabel("long chapters split & rejoin")
        chunk_hint.setObjectName("helper")
        chunk_card.body.addWidget(chunk_hint)
        adv_row.addWidget(chunk_card, 1)
        layout.addLayout(adv_row)

        names_note = Card("")
        names_note.setObjectName("note")
        names_lbl = QLabel(
            "ℹ️  Character names and place names are never translated — "
            "passed through to the model exactly as written."
        )
        names_lbl.setObjectName("helper")
        names_lbl.setWordWrap(True)
        names_note.body.addWidget(names_lbl)
        layout.addWidget(names_note)
        layout.addStretch()

        self._meta_reveal = _Reveal(self._meta_card)
        self._voice_reveal = _Reveal(self._voice_wrap)
        self.repopulate_voices(True)
        self._on_formats_changed()
        self._meta_reveal.set_visible(False, animate=False)
        self._voice_reveal.set_visible(False, animate=False)

    # ── public API ──
    def timeout_value(self) -> int:
        return self._timeout.value() if self._timeout else OLLAMA_TIMEOUT

    def max_tokens_value(self) -> int:
        if self._tokens:
            return self._tokens.value()
        return SETTINGS.get("mlx_max_tokens", 8192)

    def prefill(self, folder: str, title: str, author: str) -> None:
        if not self._folder.text():
            self._folder.setText(folder)
        if title and not self._meta_title.text():
            self._meta_title.setText(title)
        if author and not self._meta_creator.text():
            self._meta_creator.setText(author)

    def repopulate_voices(self, target_is_spanish: bool) -> None:
        """Rebuild the voice list, preserving the selection when possible."""
        previous = self._voice.currentData()
        lang = "es" if target_is_spanish else "en"
        self._voice.blockSignals(True)
        self._voice.clear()
        for entry in voices_for_language(lang):
            self._voice.addItem(entry["label"], userData=entry["value"])
        idx = self._voice.findData(previous)
        self._voice.setCurrentIndex(idx if idx >= 0 else 0)
        self._voice.blockSignals(False)

    def apply_to(self, state: wl.WizardState) -> None:
        state.formats = {k: b.isChecked() for k, b in self._fmt.items()}
        state.mp3_enabled = self._mp3.isChecked() and self._mp3.isEnabled()
        state.voice = self._voice.currentData() if state.mp3_enabled else None
        state.out_folder = self._folder.text().strip()
        state.meta_title = self._meta_title.text()
        state.meta_creator = self._meta_creator.text()
        state.meta_language = self._meta_language.text()
        state.meta_contributor = self._meta_contributor.text()
        state.chunk_words = self._chunk.value()
        state.timeout_sec = self.timeout_value()
        state.max_tokens = self.max_tokens_value()

    def load_from(self, state: wl.WizardState) -> None:
        self._folder.setText(state.out_folder)

    def set_enabled_controls(self, enabled: bool) -> None:
        for box in self._fmt.values():
            box.setEnabled(enabled)
        for w in (self._mp3, self._voice, self._folder, self._chunk,
                  self._meta_title, self._meta_creator,
                  self._meta_language, self._meta_contributor):
            w.setEnabled(enabled)
        if self._timeout:
            self._timeout.setEnabled(enabled)
        if self._tokens:
            self._tokens.setEnabled(enabled)
        if enabled:
            self._sync_mp3_gate()

    # ── internals ──
    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select output folder", self._folder.text() or str(Path.home())
        )
        if folder:
            self._folder.setText(folder)

    def _on_formats_changed(self) -> None:
        self._sync_mp3_gate()
        self._meta_reveal.set_visible(self._fmt["epub"].isChecked())
        self.changed.emit()

    def _sync_mp3_gate(self) -> None:
        """MP3 needs Kokoro installed AND .txt selected (worker.py:472)."""
        txt = self._fmt["txt"].isChecked()
        enabled = _KOKORO_AVAILABLE and txt
        self._mp3.setEnabled(enabled)
        if not enabled:
            self._mp3.setChecked(False)
        if not _KOKORO_AVAILABLE:
            self._mp3_note.setText("Kokoro is not installed — see kokoro.md.")
        elif not txt:
            self._mp3_note.setText("Requires Plain text (.txt) to be selected.")
        else:
            self._mp3_note.setText("")
        self._voice_reveal.set_visible(self._mp3.isChecked() and enabled)

    def _on_mp3_toggled(self, _state: int) -> None:
        self._voice_reveal.set_visible(
            self._mp3.isChecked() and self._mp3.isEnabled()
        )
        self.changed.emit()
```

- [ ] **Step 2: Smoke-test the gates on the real backend**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from settings import SETTINGS
from wizard_steps import StepOutput
s = StepOutput()
backend = SETTINGS["llm_backend"]
if backend == "mlx":
    assert s._tokens is not None and s._timeout is None, "mlx must show max tokens"
    assert s.max_tokens_value() == SETTINGS["mlx_max_tokens"]
else:
    assert s._timeout is not None and s._tokens is None

# MP3 must switch off when .txt is deselected
s._fmt["txt"].setChecked(False)
assert not s._mp3.isEnabled() and not s._mp3.isChecked()
assert "Plain text" in s._mp3_note.text() or "Kokoro" in s._mp3_note.text()
s._fmt["txt"].setChecked(True)

st = wl.WizardState(epub_path="/a/b.epub")
s._fmt["html"].setChecked(True)
s.apply_to(st)
assert wl.build_config(st, backend)["out_format"] == ["txt", "html"]
assert wl.build_config(st, backend)["voice"] is None
print(f"StepOutput OK on backend={backend}")
EOF
```
Expected: `StepOutput OK on backend=mlx`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard_steps.py
git add wizard_steps.py
git commit -m "feat(wizard): StepOutput with backend-aware advanced stepper"
```

---

## Task 13: `StepRun`

**Files:**
- Modify: `wizard_steps.py`

**Interfaces:**
- Consumes: `RunConsole`.
- Produces: `StepRun(QWidget)` exposing `.console: RunConsole`. Thin — the shell owns the worker and drives the console.

There is **no** segmented state control: `README.md` says it is "a prototype affordance for reviewing states — in production the state is driven by the actual job."

- [ ] **Step 1: Append `StepRun` and commit**

```python
class StepRun(QWidget):
    """Step 4 — the run console. The expanded 'drawer takes over' view."""

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        self.console = RunConsole()
        layout.addWidget(self.console, 1)

    def apply_to(self, state: wl.WizardState) -> None:
        """Step 4 holds no configuration."""

    def load_from(self, state: wl.WizardState) -> None:
        """Step 4 holds no configuration."""

    def set_enabled_controls(self, enabled: bool) -> None:
        """The console is always interactive (scroll/select)."""
```

Add `RunConsole` to the `wizard_widgets` import at the top of `wizard_steps.py`.

Run:
```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys; from PyQt6.QtWidgets import QApplication; app=QApplication(sys.argv)
from wizard_steps import StepRun
r = StepRun(); r.console.append('Ready.', 'muted'); r.console.set_progress(3, 4)
print('StepRun OK')"
pycodestyle --config=.pycodestyle --statistics wizard_steps.py
git add wizard_steps.py && git commit -m "feat(wizard): StepRun console panel"
```
Expected: `StepRun OK`

---

## Task 14: `wizard.py` — shell, navigation, validation gating

**Files:**
- Create: `wizard.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `WizardWindow(QMainWindow)`, `main()`. Worker wiring lands in Task 15.

- [ ] **Step 1: Create `wizard.py`**

```python
#!/usr/bin/env python3
"""
wizard.py
---------
Entry point for the BookWeaver Guided Wizard frontend.

    python wizard.py

Runs alongside the classic UI (`python main.py`), which is untouched. Both
drive the same ProcessingWorker.

Must not import tts (torch) or llm (mlx) at startup — availability is probed
with importlib.util.find_spec, exactly as app.py does.
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from settings import SETTINGS
from wizard_steps import StepBook, StepOutput, StepRun, StepTransform
from wizard_theme import (
    WIZARD_STYLESHEET, W_AMBER, W_APP_BG, W_SURFACE, W_TEXT, W_WINDOW_BG,
    load_caveat,
)
from wizard_widgets import StepRail

_STEP_NEXT_LABEL = {1: "Next → Transform", 2: "Next → Output", 3: "Next → Run"}


class WizardWindow(QMainWindow):
    """The four-step shell: header, rail, recap, content stack, pinned footer."""

    def __init__(self, caveat: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BookWeaver")
        self.resize(860, 724)
        self.setMinimumSize(760, 640)

        self.state = wl.WizardState()
        self.state.model = SETTINGS["default_model"]
        self._backend = SETTINGS.get("llm_backend", "ollama")
        self._worker = None
        self._resume_state: dict | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_rail())

        self._recap = QLabel("")
        self._recap.setObjectName("recapLine")
        self._recap.setContentsMargins(26, 3, 26, 0)
        outer.addWidget(self._recap)

        outer.addWidget(self._build_content(caveat), 1)
        outer.addWidget(self._build_footer())

        self._go_to(1)

    # ── construction ──
    def _build_header(self) -> QWidget:
        wrap = QWidget()
        box = QVBoxLayout(wrap)
        box.setContentsMargins(26, 17, 26, 0)
        box.setSpacing(2)
        title = QLabel("BookWeaver")
        title.setObjectName("appTitle")
        box.addWidget(title)
        sub = QLabel("EPUB → Spanish rewriter via local LLM")
        sub.setObjectName("appSubtitle")
        box.addWidget(sub)
        rule = QFrame()
        rule.setObjectName("amberRule")
        rule.setFixedHeight(2)
        box.addSpacing(13)
        box.addWidget(rule)
        return wrap

    def _build_rail(self) -> QWidget:
        wrap = QWidget()
        box = QVBoxLayout(wrap)
        box.setContentsMargins(26, 16, 26, 4)
        self._rail = StepRail()
        self._rail.stepClicked.connect(self._go_to)
        box.addWidget(self._rail)
        return wrap

    def _build_content(self, caveat: str | None) -> QWidget:
        self._steps = {
            1: StepBook(caveat),
            2: StepTransform(caveat),
            3: StepOutput(caveat),
            4: StepRun(caveat),
        }
        self._steps[1].changed.connect(self._on_step1_changed)
        self._steps[2].changed.connect(self._sync)
        self._steps[2].languageChanged.connect(self._on_language_changed)
        self._steps[3].changed.connect(self._sync)

        self._stack = QStackedWidget()
        for i in (1, 2, 3, 4):
            self._stack.addWidget(self._steps[i])

        scroll = QScrollArea()
        scroll.setObjectName("contentArea")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._stack)
        scroll.setContentsMargins(26, 18, 26, 22)
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        row = QHBoxLayout(footer)
        row.setContentsMargins(26, 13, 26, 13)
        row.setSpacing(14)

        self._back = QPushButton("← Back")
        self._back.setObjectName("ghostBtn")
        self._back.clicked.connect(lambda: self._go_to(self.state.step - 1))
        row.addWidget(self._back)

        self._clear = QPushButton("Clear log")
        self._clear.setObjectName("ghostBtn")
        self._clear.clicked.connect(self._steps[4].console.clear_log)
        row.addWidget(self._clear)

        self._drawer = QLabel("▸ run drawer · idle — expands & takes over on Start")
        self._drawer.setObjectName("helper")
        row.addWidget(self._drawer)
        row.addStretch()

        self._abort = QPushButton("Abort")
        self._abort.setObjectName("dangerBtn")
        self._abort.setEnabled(False)
        self._abort.clicked.connect(self._on_abort)
        row.addWidget(self._abort)

        self._resume = QPushButton("⏩ Resume")
        self._resume.clicked.connect(self._on_resume)
        self._resume.setVisible(False)
        row.addWidget(self._resume)

        self._next = QPushButton("Next →")
        self._next.clicked.connect(lambda: self._go_to(self.state.step + 1))
        row.addWidget(self._next)

        self._start = QPushButton("▶ Start")
        self._start.setObjectName("primaryBtn")
        self._start.clicked.connect(self._on_start)
        row.addWidget(self._start)
        return footer

    # ── navigation & sync ──
    def _go_to(self, step: int) -> None:
        step = max(1, min(4, step))
        self._collect()
        self.state.step = step
        self._stack.setCurrentWidget(self._steps[step])
        self._steps[step].load_from(self.state)
        self._sync()

    def _collect(self) -> None:
        for widget in self._steps.values():
            widget.apply_to(self.state)

    def _on_step1_changed(self) -> None:
        self._collect()
        if self.state.epub_path:
            title, author = self._steps[1].read_book_metadata(self.state.epub_path)
            from pathlib import Path
            self._steps[3].prefill(str(Path(self.state.epub_path).parent),
                                   title, author)
        self._sync()

    def _on_language_changed(self) -> None:
        self._collect()
        self._steps[3].repopulate_voices(
            wl.derive_target_is_spanish(self.state.mode, self.state.key_ideas_lang)
        )
        self._sync()

    def _sync(self) -> None:
        """Recompute every derived surface from state. One source of truth."""
        self._collect()
        step = self.state.step
        errors = wl.validation_errors(self.state)
        error_steps = {s for s, _ in errors}
        completed = {i for i in range(1, step) if i not in error_steps}
        self._rail.set_state(step, completed, error_steps)

        if step >= 2 and self.state.epub_path:
            self._recap.setText(
                wl.recap_text(self.state, self._steps[1].model_label()) + "  ·  edit"
            )
            self._recap.setVisible(True)
        else:
            self._recap.setVisible(False)

        running = self.state.run_state in ("running", "aborting")
        self._back.setVisible(step > 1 and not running)
        self._next.setVisible(step < 4 and not running)
        self._next.setText(_STEP_NEXT_LABEL.get(step, "Next →"))
        self._clear.setVisible(step == 4)
        self._drawer.setVisible(step < 4 and not running)

        self._start.setEnabled(not errors and not running)
        self._start.setToolTip(" · ".join(msg for _, msg in errors))
        if running:
            self._start.setText("● Running…")
        elif self.state.run_state in ("success", "failed", "aborted"):
            self._start.setText("▶ Start over")
        else:
            self._start.setText("▶ Start")

        self._abort.setEnabled(self.state.run_state == "running")
        if self.state.run_state == "aborting":
            self._abort.setText("Stopping…")
        else:
            self._abort.setText("Abort")
        self._resume.setVisible(self._resume_state is not None and not running)

    # ── worker hooks (filled in Task 15) ──
    def _on_start(self) -> None:
        raise NotImplementedError

    def _on_abort(self) -> None:
        raise NotImplementedError

    def _on_resume(self) -> None:
        raise NotImplementedError


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(WIZARD_STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(W_WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(W_APP_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(W_SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(W_AMBER))
    app.setPalette(palette)

    win = WizardWindow(caveat=load_caveat())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test navigation and the validation gate**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from wizard import WizardWindow
w = WizardWindow()
# Empty state => Start disabled, step 1 flagged, step 3 flagged.
assert not w._start.isEnabled()
assert "Select an EPUB file" in w._start.toolTip()
for s in (2, 3, 4, 1):
    w._go_to(s); assert w.state.step == s
# Give it a book and Start unblocks.
w.state.epub_path = "/books/x.epub"
w.state.chapters = [wl.ChapterRow(0, "One")]
w._steps[1]._path.setText("/books/x.epub")
w._steps[1]._list.set_chapters(w.state.chapters)
w._sync()
assert w._start.isEnabled(), w._start.toolTip()
# Drop every format => blocked again, step 3 flagged.
for b in w._steps[3]._fmt.values(): b.setChecked(False)
w._sync()
assert not w._start.isEnabled()
assert "output format" in w._start.toolTip()
print("WizardWindow shell OK")
EOF
```
Expected: `WizardWindow shell OK`

- [ ] **Step 3: Lint and commit**

```bash
pycodestyle --config=.pycodestyle --statistics wizard.py
git add wizard.py
git commit -m "feat(wizard): shell, step navigation, validation gating"
```

---

## Task 15: Worker wiring — start, abort, resume, finish

**Files:**
- Modify: `wizard.py`

**Interfaces:**
- Consumes: `worker.ProcessingWorker` (lazy import), `wl.build_config`, `wl.resume_hint`.
- Produces: the three `NotImplementedError` stubs from Task 14 replaced.

Lifecycle per the spec: `idle → running → success | failed | aborting → aborted`. Aborted runs stay resumable — `completed_results` is populated identically.

- [ ] **Step 1: Replace the three stubs in `wizard.py`**

```python
    # ── worker lifecycle ──
    def _start_worker(self, cfg: dict) -> None:
        from worker import ProcessingWorker      # lazy: never at import time
        console = self._steps[4].console
        self._worker = ProcessingWorker(cfg)
        self._worker.log.connect(console.append)
        self._worker.progress.connect(console.set_progress)
        self._worker.finished.connect(self._on_finished)
        self.state.run_state = "running"
        self._go_to(4)
        self._set_controls_enabled(False)
        self._worker.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self._steps.values():
            widget.set_enabled_controls(enabled)

    def _on_start(self) -> None:
        self._collect()
        if wl.validation_errors(self.state):
            return                       # Start is disabled; belt and braces
        self._resume_state = None
        self._steps[4].console.reset()
        # Capture the backend once, so a resume can never flip it mid-book.
        cfg = wl.build_config(self.state, self._backend)
        self._steps[4].console.append(
            f"📖  Starting: {len(cfg['selected_chapters'])} chapter(s), "
            f"mode={cfg['mode']}, backend={cfg['backend']}",
            "muted",
        )
        self._start_worker(cfg)

    def _on_abort(self) -> None:
        if not self._worker:
            return
        self._worker.abort()
        self.state.run_state = "aborting"
        # _abort is polled at chunk boundaries (worker.py:187,219,289,335),
        # never mid-generation. On mlx an in-flight call cannot be
        # interrupted, so be honest about the latency.
        self._steps[4].console.append(
            "·  Abort requested — will stop after the current chunk.", "muted"
        )
        self._sync()

    def _on_resume(self) -> None:
        if not self._resume_state:
            return
        cfg = {
            **self._resume_state["config"],
            "timeout":       self._steps[3].timeout_value(),
            "max_tokens":    self._steps[3].max_tokens_value(),
            "chunk_size":    self.state.chunk_words,
            "resume_from":   self._resume_state["from_chapter"],
            "prior_results": self._resume_state["results"],
        }
        self._steps[4].console.append(
            f"⏩  Resuming from chapter {self._resume_state['from_chapter'] + 1}…",
            "info",
        )
        self._resume_state = None
        self._start_worker(cfg)

    def _on_finished(self, success: bool, path: str) -> None:
        console = self._steps[4].console
        worker, self._worker = self._worker, None
        aborting = self.state.run_state == "aborting"

        if success:
            self.state.run_state = "success"
            self._resume_state = None
            console.append(f"\n🎉  All done!  Output: {path}", "success")
        else:
            self.state.run_state = "aborted" if aborting else "failed"
            if not aborting:
                console.append("\n✗  Run failed.", "error")
            partial = list(getattr(worker, "completed_results", []) or [])
            if partial:
                # Aborted runs are resumable too: completed_results is
                # populated identically on every early exit.
                self._resume_state = {
                    "config": worker.config,
                    "from_chapter": worker.failed_at_chapter,
                    "results": partial,
                }
                console.append(
                    f"💾  {len(partial)} chapter(s) saved. "
                    f"{wl.resume_hint(self._backend)}",
                    "warning",
                )

        self._set_controls_enabled(True)
        self._sync()
```

- [ ] **Step 2: Verify the resume config round-trips through the worker**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard_logic as wl
from worker import ProcessingWorker

base = wl.build_config(
    wl.WizardState(
        epub_path="/books/x.epub",
        chapters=[wl.ChapterRow(i, f"C{i}") for i in range(5)],
        model="m", out_folder="/out", max_tokens=8192, timeout_sec=1200,
    ), "mlx")
resumed = {**base, "timeout": 900, "max_tokens": 2048,
           "chunk_size": 1500, "resume_from": 3, "prior_results": [("t", "x")]}
w = ProcessingWorker(resumed)
assert w._max_tokens == 2048, w._max_tokens   # the override must reach the worker
assert w._timeout == 900
assert w._chunk_size == 1500
assert w._backend == "mlx"                    # never flips on resume
assert set(base) == wl.CONFIG_KEYS
print("resume round-trip OK — max_tokens reaches the worker")
EOF
```
Expected: `resume round-trip OK — max_tokens reaches the worker`

This is the assertion that proves the mlx failure copy ("Adjust settings, then press Resume") is *true* rather than decorative.

- [ ] **Step 3: Verify the wizard never imports torch or mlx at startup**

Run:
```bash
QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import wizard
w = wizard.WizardWindow()
heavy = [m for m in sys.modules if m.split(".")[0] in ("torch", "mlx_lm", "mlx_vlm", "tts", "llm")]
assert not heavy, f"wizard startup dragged in heavy modules: {heavy}"
print("wizard startup is lean:", "no torch/mlx/tts/llm")
EOF
```
Expected: `wizard startup is lean: no torch/mlx/tts/llm`

- [ ] **Step 4: Full suite + lint + commit**

```bash
pytest -q     # 1 pre-existing failure expected
pycodestyle --config=.pycodestyle --statistics wizard.py
git add wizard.py
git commit -m "feat(wizard): worker wiring — start, abort, resume, finish"
```

---

## Task 16: Guard block, docs, and end-to-end verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the class-boundary guard in `CLAUDE.md`**

CLAUDE.md's "Known historical issues" pins the expected `grep -n "^class "` output. Without this edit the guard false-positives on every future run.

Run `grep -n "^class " *.py` and replace the expected-output block in `CLAUDE.md` with its real output. It should now include:

```
wizard.py:         class WizardWindow(QMainWindow)
wizard_steps.py:   class StepBook(QWidget)
wizard_steps.py:   class StepTransform(QWidget)
wizard_steps.py:   class StepOutput(QWidget)
wizard_steps.py:   class StepRun(QWidget)
wizard_widgets.py: class Card(QFrame)
wizard_widgets.py: class RunConsole(QWidget)
wizard_widgets.py: class WizardSlider(QWidget)
wizard_widgets.py: class StepRail(QWidget)
wizard_widgets.py: class ModeTileGrid(QWidget)
wizard_widgets.py: class TriStateChapterList(QWidget)
```

`wizard_logic.py`'s `ChapterRow` and `WizardState` are dataclasses and also
match `^class `, so include them. `_Reveal`, `_ProgressPill`, `_MlxLmRuntime`
etc. are private and do not (they do not start at column 0 with `class ` —
verify with the real grep output rather than assuming).

- [ ] **Step 2: Add a wizard section to `CLAUDE.md`'s file map**

Insert into the file-map table, after the `widgets.py` row:

```markdown
| `wizard.py` | **New wizard frontend** entry point + shell (`python wizard.py`). Coexists with `main.py`/`app.py`. | For wizard shell/nav changes |
| `wizard_theme.py` | Wizard palette (`wizard_colors` in JSON), stylesheet, Caveat font | For wizard styling |
| `wizard_logic.py` | Pure, Qt-free wizard state + the 22-key `build_config` worker contract | For wizard behaviour changes |
| `wizard_widgets.py` | Wizard's custom-painted widgets (sliders, tiles, rail, console) | For new/changed wizard widgets |
| `wizard_steps.py` | One QWidget per wizard step | For step content changes |
```

Also extend the architecture-rules import-flow block with the wizard's flow (copy from this plan's Global Constraints), and note under "Timeout" that `max_tokens` is now a per-run config key overridable by the wizard's Step-3 stepper.

- [ ] **Step 3: Verify BOTH frontends still run**

Run:
```bash
grep -n "^class " *.py
pytest -q
pycodestyle --config=.pycodestyle --statistics *.py
QT_QPA_PLATFORM=offscreen python -c "
import sys; from PyQt6.QtWidgets import QApplication; a=QApplication(sys.argv)
import app, wizard
app.BookWeaverApp(); wizard.WizardWindow()
print('both frontends construct')"
```
Expected: `pytest` shows exactly 1 failure (`test_settings.py::TestOllamaTimeout::test_defaults_when_missing`, pre-existing); `pycodestyle` clean; `both frontends construct`.

- [ ] **Step 4: End-to-end acceptance run (manual, requires a real EPUB)**

Launch the wizard for real:

```bash
python wizard.py
```

Walk this checklist. Each item is a spec requirement:

1. Step 1: Browse → pick a short EPUB. Chapter list fills; meta reads `N / N selected`; output folder pre-fills to the book's directory.
2. Untick 2 chapters → master checkbox goes tri-state; recap (visible from step 2) reads `N-2 / N chapters`.
3. Step 2: click each of the four mode tiles. Depth card collapses smoothly on **Full translation** only. Notes appear for Full translation and Summarise only. Key-ideas language card appears for Summary + key ideas.
4. With **Summarise only**, the Spanish level card disappears and the recap drops `B2`. Switch back → both return.
5. With **Summary + key ideas**, flip Spanish ↔ English. The Step-3 voice list changes language. The Spanish level card follows.
6. Creativity slider at 5 must read `temp ≈ 0.68` (**not** `0.44`) and show the `✦ sweet spot` pill. At 9 the knob turns red, not amber.
7. Step 3 shows **Max tokens per call** (mlx), not Timeout. Untick `.txt` → MP3 disables with "Requires Plain text (.txt) to be selected."
8. Tick `.epub` → the EPUB-metadata card reveals with Title/Author pre-filled.
9. Untick every format → Start disables, step-3 badge flags red, tooltip names the problem.
10. Press Start → jumps to step 4; Start reads `● Running…`; Abort enables; the log streams.
11. Press Abort → Abort reads `Stopping…` and disables; a muted "will stop after the current chunk" line appears; the run ends and Resume appears.
12. Set `Max tokens` to `256` and Start a fresh run → a chapter should fail. The `💾 N chapter(s) saved. Adjust settings, then press Resume.` line must **not** mention the timeout.
13. Raise `Max tokens` to `8192`, press **Resume** → the run continues from the failed chapter and completes. This is the assertion that the `max_tokens` resume override actually reaches the worker.
14. Confirm the written output files exist and are identical in shape to a `python main.py` run of the same config.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — wizard frontend file map, import flow, class guard"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task:

| Spec § | Task |
|---|---|
| §2 constraints: `worker.py` 3-line diff | 4 |
| §2 constraints: `wizard_colors` additive block | 1 |
| §2 constraints: `assets/` | 3 |
| §3 module decomposition + import flow | 1, 5, 7, 10, 14; enforced by the Qt-free check in Task 5 Step 5 and the lean-startup check in Task 15 Step 3 |
| §4 the 22-key contract, enum maps, derivations | 5, 6 |
| §4 resume round-trip incl. `max_tokens` | 15 (verified in Step 2) |
| §5 `WizardState`, `ChapterRow` | 5 |
| §5 `validation_errors` → 3 consumers | 5 (logic), 14 (Start + tooltip + badges) |
| §5 run lifecycle incl. resumable abort | 15 |
| §5 `resume_hint` backend-aware copy | 5, 15 |
| §6 palette, `RAMP`, `LOG_COLORS`, dropped `head` | 1 |
| §6 stylesheet | 2 |
| §6 Caveat + variable-font risk + fallback | 3 |
| §7 dropped title bar / segmented control | 13, 14 (neither is built) |
| §7 dynamic backend label, `MODEL (MLX)` | 10 |
| §7 backend-aware Step-3 stepper | 12 |
| §7 `temp ≈ 0.68` not `0.44` | 5 (test), 8 (smoke-test) |
| §7 recap truncation + selection fraction | 5 |
| §7 creativity ramp 9–10 = error | 5 (test asserts it differs from `widgets.py`) |
| §7 animated reveals, 180 ms OutCubic | 11 |
| §7 all conditional reveals | 11, 12 |
| §7 sliders | 8 |
| §8 test coverage table | 1, 3, 4, 5, 6 |
| §9 verification commands + class guard | 16 |

**Two spec gaps found and closed in this plan:**

1. **Palette was incomplete.** §6 named 23 `wizard_colors` keys, but the design uses 11 more hexes it never named (slider track, knob ring, row hover, fill-gradient start, log-info, log-muted, disabled-button bg/fg, danger bg/border, completed-badge fill). Shipping §6 verbatim would have forced hardcoded hexes into `wizard_widgets.py`, violating CLAUDE.md rule #2. All 11 are added in Task 1 with a note.

2. **The spec said "21 keys"; it is 22.** Corrected in the spec before writing this plan (`app.py` emits 21; the wizard adds `max_tokens`). Task 6 asserts `len(CONFIG_KEYS) == 22` and that `CONFIG_KEYS - app_keys == {"max_tokens"}`.

**Type consistency.** Checked across tasks: `ChapterRow(index, title, checked)` is constructed identically in Tasks 5, 9, 10; `TriStateChapterList.rows()` returns `list[ChapterRow]` and `set_chapters()` consumes it. `WizardSlider.value()/set_value()` used consistently in 8, 11. `StepOutput.timeout_value()/max_tokens_value()` defined in 12, consumed in 15. `RunConsole.append(msg, level)` matches `worker.log`'s `(str, str)` signature exactly, so `self._worker.log.connect(console.append)` in Task 15 type-checks. `apply_to`/`load_from`/`set_enabled_controls` exist on all four steps (`StepRun`'s are no-ops, defined in Task 13) so the loops in `_collect()` and `_set_controls_enabled()` cannot `AttributeError`.

**Placeholder scan.** No TBD/TODO. Every code step carries real code. One deliberate correction is inline in Task 4 Step 1, where the first draft of `test_config_key_overrides_settings` is replaced by the simpler constructor form — the instruction says to keep only the latter.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-wizard-frontend.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
