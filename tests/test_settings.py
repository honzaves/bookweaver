"""
tests/test_settings.py
----------------------
Unit tests for settings.py and bookweaver.json.
"""

import json
from pathlib import Path

import pytest

import settings as settings_module
from settings import (
    C_AMBER, C_AMBER_DIM, C_BG, C_BORDER, C_ERROR, C_MUTED,
    C_SUCCESS, C_SURFACE, C_SURFACE2, C_TEXT, C_WARNING,
    SETTINGS, STYLESHEET, creativity_to_temperature,
    _load_config, _build,
)


# ──────────────────────────────────────────────────────────────
#  creativity_to_temperature
# ──────────────────────────────────────────────────────────────
class TestCreativityToTemperature:
    def test_minimum(self):
        assert creativity_to_temperature(1) == pytest.approx(0.1, abs=1e-6)

    def test_maximum(self):
        assert creativity_to_temperature(10) == pytest.approx(1.4, abs=1e-6)

    def test_monotonically_increasing(self):
        temps = [creativity_to_temperature(c) for c in range(1, 11)]
        assert temps == sorted(temps)

    def test_all_in_range(self):
        for c in range(1, 11):
            assert 0.1 <= creativity_to_temperature(c) <= 1.4

    def test_rounded_to_two_dp(self):
        for c in range(1, 11):
            t = creativity_to_temperature(c)
            assert t == round(t, 2)


# ──────────────────────────────────────────────────────────────
#  _load_config
# ──────────────────────────────────────────────────────────────
def _write_json(path: Path, data: dict) -> Path:
    p = path / "bookweaver.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p

MINIMAL_CFG = {
    "colors": {
        "bg": "#000000", "surface": "#111111", "surface2": "#222222",
        "border": "#333333", "amber": "#ffaa00", "amber_dim": "#885500",
        "text": "#ffffff", "muted": "#888888", "success": "#00ff00",
        "warning": "#ffff00", "error": "#ff0000", "sweet": "#00ff00",
    },
    "models": [{"label": "Test", "value": "test:1b"}],
    "default_model": "test:1b",
}

class TestLoadConfig:
    def test_valid_file_returns_dict(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        result = _load_config(p)
        assert isinstance(result, dict)

    def test_loads_colors(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        result = _load_config(p)
        assert result["colors"]["bg"] == "#000000"

    def test_loads_models(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        result = _load_config(p)
        assert result["models"] == MINIMAL_CFG["models"]

    def test_missing_file_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit, match="not found"):
            _load_config(tmp_path / "nope.json")

    def test_malformed_json_raises_system_exit(self, tmp_path):
        p = tmp_path / "bookweaver.json"
        p.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(SystemExit, match="Invalid JSON"):
            _load_config(p)


# ──────────────────────────────────────────────────────────────
#  _build — module constant population
# ──────────────────────────────────────────────────────────────
class TestBuild:
    def test_colour_constants_set_from_json(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert settings_module.C_BG == "#000000"
        assert settings_module.C_AMBER == "#ffaa00"

    def test_settings_dict_populated(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert settings_module.SETTINGS["default_model"] == "test:1b"
        assert settings_module.SETTINGS["models"] == MINIMAL_CFG["models"]

    def test_stylesheet_contains_loaded_colours(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert "#000000" in settings_module.STYLESHEET
        assert "#ffaa00" in settings_module.STYLESHEET

    def test_restores_defaults_after_test(self, tmp_path):
        """Rebuild from the real config so other tests aren't affected."""
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        _build()  # restore
        assert settings_module.C_BG == "#111210"


# ──────────────────────────────────────────────────────────────
#  Colour constants (loaded from real bookweaver.json)
# ──────────────────────────────────────────────────────────────
class TestColourConstants:
    COLOURS = {
        "C_BG": C_BG, "C_SURFACE": C_SURFACE, "C_SURFACE2": C_SURFACE2,
        "C_BORDER": C_BORDER, "C_AMBER": C_AMBER, "C_AMBER_DIM": C_AMBER_DIM,
        "C_TEXT": C_TEXT, "C_MUTED": C_MUTED, "C_SUCCESS": C_SUCCESS,
        "C_WARNING": C_WARNING, "C_ERROR": C_ERROR,
    }

    def test_all_are_hex_strings(self):
        for name, value in self.COLOURS.items():
            assert isinstance(value, str) and value.startswith("#"), name

    def test_all_valid_hex_length(self):
        for name, value in self.COLOURS.items():
            assert len(value) in {4, 7, 9}, f"{name}: {value}"

    def test_all_valid_hex_digits(self):
        for name, value in self.COLOURS.items():
            assert all(c in "0123456789abcdefABCDEF" for c in value[1:]), name

    # Colours that must appear in the stylesheet (widget-only colours excluded).
    STYLESHEET_COLOURS = {"C_BG", "C_SURFACE", "C_SURFACE2", "C_BORDER",
                          "C_AMBER", "C_AMBER_DIM", "C_TEXT", "C_MUTED", "C_ERROR"}

    def test_stylesheet_references_each_colour(self):
        for name in self.STYLESHEET_COLOURS:
            value = self.COLOURS[name]
            assert value in STYLESHEET, f"{name} ({value}) not found in STYLESHEET"


# ──────────────────────────────────────────────────────────────
#  SETTINGS dict
# ──────────────────────────────────────────────────────────────
class TestSettings:
    def test_is_dict(self):
        assert isinstance(SETTINGS, dict)

    def test_has_models_list(self):
        assert isinstance(SETTINGS.get("models"), list)
        assert len(SETTINGS["models"]) > 0

    def test_each_model_has_label_and_value(self):
        for m in SETTINGS["models"]:
            assert "label" in m and "value" in m

    def test_default_model_in_models_list(self):
        values = [m["value"] for m in SETTINGS["models"]]
        assert SETTINGS["default_model"] in values
