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
