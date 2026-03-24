"""
settings.py
-----------
Loads bookweaver.json and exposes colour constants, the Qt stylesheet,
and the SETTINGS dict to the rest of the application.

To change colours or models, edit bookweaver.json — no Python changes needed.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "bookweaver.json"


# ──────────────────────────────────────────────────────────────
#  CONFIG LOADER
# ──────────────────────────────────────────────────────────────
def _load_config(path: Path = _CONFIG_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"[BookWeaver] Config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[BookWeaver] Invalid JSON in config: {exc}")


def _build(path: Path = _CONFIG_PATH) -> None:
    """Load config and populate all module-level constants."""
    global C_BG, C_SURFACE, C_SURFACE2, C_BORDER, C_AMBER, C_AMBER_DIM
    global C_TEXT, C_MUTED, C_SUCCESS, C_WARNING, C_ERROR, C_SWEET
    global STYLESHEET, SETTINGS, OLLAMA_TIMEOUT

    cfg = _load_config(path)
    c = cfg["colors"]

    C_BG        = c["bg"]
    C_SURFACE   = c["surface"]
    C_SURFACE2  = c["surface2"]
    C_BORDER    = c["border"]
    C_AMBER     = c["amber"]
    C_AMBER_DIM = c["amber_dim"]
    C_TEXT      = c["text"]
    C_MUTED     = c["muted"]
    C_SUCCESS   = c["success"]
    C_WARNING   = c["warning"]
    C_ERROR     = c["error"]
    C_SWEET     = c["sweet"]

    STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 13px;
}}
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
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C_BORDER};
}}
"""

    SETTINGS = {
        "models":        cfg["models"],
        "default_model": cfg["default_model"],
    }

    OLLAMA_TIMEOUT = int(cfg.get("ollama_timeout", 600))


# Initialise module-level constants from the default config path.
_build()


# ──────────────────────────────────────────────────────────────
#  CREATIVITY → TEMPERATURE MAPPING
# ──────────────────────────────────────────────────────────────
def creativity_to_temperature(creativity: int) -> float:
    """Map creativity 1–10 linearly to Ollama temperature 0.1–1.4."""
    return round(0.1 + (creativity - 1) * (1.3 / 9), 2)
