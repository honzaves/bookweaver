"""
wizard_theme.py
---------------
Palette, stylesheet, and decorative font for the Guided Wizard frontend.

Loads bookweaver.json["wizard_colors"] directly rather than importing
settings.py — that module's _build() runs at import time and populates the
*old* UI's globals. Keeping the loaders separate keeps the two themes from
sharing mutable state.

Imports stdlib at module scope; PyQt6.QtGui is imported lazily if needed.
Never settings, never app, never worker.
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
    "muted": W_MUTED,
    "neutral": W_TEXT_SECONDARY,
    "green": W_SUCCESS,
    "warning": W_WARNING,
    "error": W_ERROR,
}

# Exactly the five levels ProcessingWorker.log emits (worker.py:44-45).
# The design also lists a "head" severity; nothing emits it, so it is dropped.
LOG_COLORS: dict[str, str] = {
    "info": W_LOG_INFO,
    "muted": W_LOG_MUTED,
    "success": W_SUCCESS,
    "warning": W_WARNING,
    "error": W_ERROR,
}

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

QScrollArea#contentArea {{
    background: transparent;
    border: none;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {W_AMBER_DIM}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""
