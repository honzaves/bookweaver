"""
tests/test_tts.py
-----------------
Unit tests for tts.py pure helpers and the optional-import gate, plus the
mode → target-language plumbing in settings.py.

Real Kokoro synthesis is not unit-tested (slow, GB-sized download) — the
manual smoke test in kokoro.md §3.3 covers it.
"""

import importlib
import json
import sys
from types import ModuleType

import pytest

import settings as settings_module
from settings import TARGET_LANG, voices_for_language, _build

import tts


# ──────────────────────────────────────────────────────────────
#  Optional-import gate
# ──────────────────────────────────────────────────────────────
class TestImportGate:
    def test_tts_import_gate_when_kokoro_missing(self):
        with pytest.MonkeyPatch.context() as mp:
            # None in sys.modules makes `import kokoro` raise ImportError.
            mp.setitem(sys.modules, "kokoro", None)
            mod = importlib.reload(tts)
            assert mod.TTS_AVAILABLE is False
            assert isinstance(mod.TTS_IMPORT_ERROR, ImportError)
        importlib.reload(tts)  # restore for other tests

    def test_gate_reports_available_when_imports_succeed(self):
        # Inject scoped stubs for any gate import that is missing here
        # (numpy is deliberately not stubbed in conftest).
        with pytest.MonkeyPatch.context() as mp:
            for name in ("kokoro", "soundfile", "lameenc", "mutagen", "numpy"):
                if name not in sys.modules:
                    mp.setitem(sys.modules, name, ModuleType(name))
            mod = importlib.reload(tts)
            assert mod.TTS_AVAILABLE is True
            assert mod.TTS_IMPORT_ERROR is None
        importlib.reload(tts)  # restore for other tests

    def test_synthesise_book_raises_when_unavailable(self, tmp_path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "kokoro", None)
            mod = importlib.reload(tts)
            with pytest.raises(RuntimeError, match="kokoro.md"):
                mod.synthesise_book(
                    chapters=[("Capítulo 1", "Hola.")],
                    voice="ef_dora",
                    lang_code="e",
                    out_path=tmp_path / "x.mp3",
                )
        importlib.reload(tts)


# ──────────────────────────────────────────────────────────────
#  Kokoro language-code mapping
# ──────────────────────────────────────────────────────────────
class TestKokoroLangCode:
    def test_spanish_always_e(self):
        assert tts.kokoro_lang_code("es", "ef_dora") == "e"
        assert tts.kokoro_lang_code("es", "em_alex") == "e"

    def test_lang_code_mapping_uk_voices(self):
        assert tts.kokoro_lang_code("en", "bf_emma") == "b"
        assert tts.kokoro_lang_code("en", "bm_george") == "b"

    def test_us_voices_map_to_a(self):
        assert tts.kokoro_lang_code("en", "af_heart") == "a"
        assert tts.kokoro_lang_code("en", "am_michael") == "a"


# ──────────────────────────────────────────────────────────────
#  Mode → target language mapping
# ──────────────────────────────────────────────────────────────
class TestTargetLang:
    def test_target_lang_mapping(self):
        assert TARGET_LANG["summarise_rewrite"] == "es"
        assert TARGET_LANG["translate"] == "es"
        assert TARGET_LANG["summarise_only"] == "en"

    def test_covers_all_modes(self):
        assert set(TARGET_LANG) == {
            "summarise_rewrite", "translate", "summarise_only"
        }


# ──────────────────────────────────────────────────────────────
#  voices_for_language (config-driven)
# ──────────────────────────────────────────────────────────────
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


class TestVoicesForLanguage:
    def _build_with(self, tmp_path, extra: dict):
        p = tmp_path / "bookweaver.json"
        p.write_text(json.dumps({**MINIMAL_CFG, **extra}), encoding="utf-8")
        _build(p)

    def test_voices_for_language_from_settings(self, tmp_path):
        voices = {
            "es": [{"label": "Dora (female)", "value": "ef_dora"}],
            "en": [{"label": "Heart (female, US)", "value": "af_heart"}],
        }
        self._build_with(tmp_path, {"voices": voices})
        try:
            assert voices_for_language("es") == voices["es"]
            assert voices_for_language("en") == voices["en"]
        finally:
            _build()  # restore real config

    def test_unknown_language_returns_empty_list(self, tmp_path):
        self._build_with(tmp_path, {"voices": {"es": []}})
        try:
            assert voices_for_language("fr") == []
        finally:
            _build()

    def test_missing_voices_block_returns_empty_list(self, tmp_path):
        self._build_with(tmp_path, {})
        try:
            assert voices_for_language("es") == []
        finally:
            _build()

    def test_real_config_has_voices_for_both_languages(self):
        for lang in ("es", "en"):
            voices = voices_for_language(lang)
            assert voices, f"no voices configured for {lang}"
            for v in voices:
                assert "label" in v and "value" in v

    def test_real_config_tts_defaults_exist(self):
        tts_cfg = settings_module.SETTINGS.get("tts", {})
        assert tts_cfg.get("default_voice_es")
        assert tts_cfg.get("default_voice_en")
