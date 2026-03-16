"""
settings.py
-----------
Colour palette, Qt stylesheet, and settings loader.

All other modules import colours and SETTINGS from here.
The JSON settings file lives next to this file and controls
the model list without requiring any code changes.
"""

import json
from pathlib import Path


# ──────────────────────────────────────────────────────────────
#  COLOUR PALETTE
# ──────────────────────────────────────────────────────────────
C_BG = "#111210"
C_SURFACE = "#1c1d1b"
C_SURFACE2 = "#252620"
C_BORDER = "#2e2f2a"
C_AMBER = "#d4a853"
C_AMBER_DIM = "#8a6a2e"
C_TEXT = "#e8e4d9"
C_MUTED = "#7a7870"
C_SUCCESS = "#7aab6e"
C_WARNING = "#c98d3a"
C_ERROR = "#c0604a"
C_SWEET = "#7aab6e"  # sweet-spot highlight on sliders


# ──────────────────────────────────────────────────────────────
#  QT STYLESHEET
# ──────────────────────────────────────────────────────────────
STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 13px;
}}

/* ── GROUP BOXES ── */
QGroupBox {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    margin-top: 18px;
    padding: 12px 14px 10px 14px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: {C_MUTED};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: -1px;
    padding: 0 6px;
    background-color: {C_SURFACE};
}}

/* ── LABELS ── */
QLabel {{
    background: transparent;
    color: {C_TEXT};
}}
QLabel#muted {{
    color: {C_MUTED};
    font-size: 11px;
}}
QLabel#amber {{
    color: {C_AMBER};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.5px;
}}

/* ── LINE EDIT ── */
QLineEdit {{
    background-color: {C_SURFACE2};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {C_TEXT};
    selection-background-color: {C_AMBER_DIM};
}}
QLineEdit:focus {{
    border-color: {C_AMBER};
}}

/* ── COMBO BOX ── */
QComboBox {{
    background-color: {C_SURFACE2};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {C_TEXT};
    min-width: 140px;
}}
QComboBox:focus {{
    border-color: {C_AMBER};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C_MUTED};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_SURFACE2};
    border: 1px solid {C_BORDER};
    selection-background-color: {C_AMBER_DIM};
    color: {C_TEXT};
    padding: 4px;
}}

/* ── SLIDER ── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {C_BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {C_AMBER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {C_AMBER};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: #e8c070;
}}

/* ── BUTTONS ── */
QPushButton {{
    background-color: {C_SURFACE2};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 16px;
    color: {C_TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    border-color: {C_AMBER};
    color: {C_AMBER};
}}
QPushButton:pressed {{
    background-color: {C_AMBER_DIM};
}}
QPushButton#primary {{
    background-color: {C_AMBER};
    border: none;
    color: #111210;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.3px;
    padding: 10px 28px;
    border-radius: 8px;
}}
QPushButton#primary:hover {{
    background-color: #e8c070;
    color: #111210;
}}
QPushButton#primary:disabled {{
    background-color: {C_AMBER_DIM};
    color: #555;
}}
QPushButton#danger {{
    background-color: transparent;
    border: 1px solid {C_ERROR};
    color: {C_ERROR};
}}
QPushButton#danger:hover {{
    background-color: {C_ERROR};
    color: {C_TEXT};
}}

/* ── CHECKBOX & RADIO ── */
QCheckBox, QRadioButton {{
    spacing: 8px;
    color: {C_TEXT};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {C_BORDER};
    border-radius: 4px;
    background: {C_SURFACE2};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {C_AMBER};
    border-color: {C_AMBER};
}}

/* ── TEXT EDIT (log) ── */
QTextEdit {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 10px;
    color: {C_TEXT};
    font-family: "SF Mono", "Menlo", monospace;
    font-size: 12px;
    line-height: 1.5;
}}

/* ── SCROLL BARS ── */
QScrollBar:vertical {{
    background: {C_BG};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

/* ── SEPARATOR ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C_BORDER};
}}
"""


# ──────────────────────────────────────────────────────────────
#  SETTINGS LOADER
# ──────────────────────────────────────────────────────────────
_SETTINGS_PATH = Path(__file__).parent / "bookweaver_settings.json"

_DEFAULT_SETTINGS: dict = {
    "models": [
        {"label": "Gemma 3 27B  (recommended)", "value": "gemma3:27b"},
        {"label": "Llama 3.3 70B", "value": "llama3.3:70b"},
    ],
    "default_model": "gemma3:27b",
}


def load_settings() -> dict:
    """Load bookweaver_settings.json, falling back to defaults on any error."""
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for key, value in _DEFAULT_SETTINGS.items():
            data.setdefault(key, value)
        return data
    except FileNotFoundError:
        return _DEFAULT_SETTINGS.copy()
    except Exception as exc:
        print(f"[BookWeaver] Could not read settings: {exc} — using defaults.")
        return _DEFAULT_SETTINGS.copy()


# Module-level singleton — import SETTINGS from here everywhere.
SETTINGS: dict = load_settings()
