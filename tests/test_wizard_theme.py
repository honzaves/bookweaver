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
