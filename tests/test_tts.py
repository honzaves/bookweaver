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
            "summarise_rewrite", "translate", "summarise_only",
            "summarise_key_ideas",
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


# ──────────────────────────────────────────────────────────────
#  TTS text sanitization — clean_for_tts
# ──────────────────────────────────────────────────────────────
class TestCleanForTts:
    def test_strips_bracketed_digit_footnote_refs(self):
        assert tts.clean_for_tts("the war[3] ended[12].") == "the war ended."

    def test_strips_parenthetical_digit_refs(self):
        assert tts.clean_for_tts("see (1) and (23) above") == "see and above"

    def test_strips_superscript_footnote_markers(self):
        assert tts.clean_for_tts("the war³ ended⁴⁵") == "the war ended"

    def test_strips_asterisk_emphasis_keeping_word(self):
        assert tts.clean_for_tts("it was *very* **bold**") == "it was very bold"

    def test_strips_stray_trailing_asterisk(self):
        assert tts.clean_for_tts("a word* here") == "a word here"

    def test_strips_backticks(self):
        assert tts.clean_for_tts("the `code` word") == "the code word"

    def test_strips_underscore_emphasis(self):
        assert tts.clean_for_tts("it was _very_ good") == "it was very good"

    def test_preserves_snake_case_identifiers(self):
        assert tts.clean_for_tts("call snake_case here") == "call snake_case here"

    def test_strips_leading_bullet_markers(self):
        text = "- first idea\n* second idea\n• third idea"
        assert tts.clean_for_tts(text) == "first idea\nsecond idea\nthird idea"

    def test_collapses_excess_whitespace(self):
        assert tts.clean_for_tts("too    many     spaces") == "too many spaces"
        assert tts.clean_for_tts("a\n\n\n\nb") == "a\n\nb"

    def test_is_idempotent(self):
        text = "the war[3] was *very* _tense_\n- a bullet"
        once = tts.clean_for_tts(text)
        assert tts.clean_for_tts(once) == once

    def test_plain_text_is_unchanged(self):
        text = "A perfectly ordinary sentence, with punctuation!"
        assert tts.clean_for_tts(text) == text


# ──────────────────────────────────────────────────────────────
#  TTS text sanitization — segments_for_tts
# ──────────────────────────────────────────────────────────────
class TestSegmentsForTts:
    def test_no_scene_break_returns_single_cleaned_part(self):
        assert tts.segments_for_tts("Just one part.") == ["Just one part."]

    def test_splits_on_spaced_asterisk_scene_break(self):
        body = "End of scene one.\n* * *\nStart of scene two."
        assert tts.segments_for_tts(body) == [
            "End of scene one.",
            "Start of scene two.",
        ]

    def test_splits_on_various_scene_break_forms(self):
        for sep in ("***", "---", "___", "- - -"):
            body = f"before\n{sep}\nafter"
            assert tts.segments_for_tts(body) == ["before", "after"], sep

    def test_cleans_each_part(self):
        body = "the war[3] ended\n* * *\nit was *new*"
        assert tts.segments_for_tts(body) == ["the war ended", "it was new"]

    def test_drops_empty_parts(self):
        body = "real text\n* * *\n[1]\n* * *\nmore text"
        assert tts.segments_for_tts(body) == ["real text", "more text"]


# ──────────────────────────────────────────────────────────────
#  synthesise_book wiring (Kokoro seams stubbed — numpy is real)
# ──────────────────────────────────────────────────────────────
class TestSynthesiseBookWiring:
    def test_cleans_title_and_inserts_scene_break_silence(
        self, tmp_path, monkeypatch
    ):
        import numpy as np

        spoken: list[str] = []
        silences: list[int] = []
        real_silence = tts._silence

        def fake_synth(pipe, text, voice, lang_code):
            spoken.append(text)
            return np.zeros(10, dtype=np.float32)

        def fake_silence(ms):
            silences.append(ms)
            return real_silence(ms)

        monkeypatch.setattr(tts, "TTS_AVAILABLE", True)
        monkeypatch.setattr(tts, "_make_pipeline", lambda lang_code: object())
        monkeypatch.setattr(tts, "_synth", fake_synth)
        monkeypatch.setattr(tts, "_silence", fake_silence)
        monkeypatch.setattr(tts, "encode_mp3", lambda audio, sr, br: b"ID3")
        monkeypatch.setattr(tts, "_tag_mp3", lambda *a, **k: None)

        tts.synthesise_book(
            chapters=[("*Chapter* One", "scene A\n* * *\nscene B")],
            voice="ef_dora",
            lang_code="e",
            out_path=tmp_path / "x.mp3",
            scene_break_silence_ms=800,
        )

        # Title is cleaned; body is split into two spoken parts.
        assert spoken == ["Chapter One", "scene A", "scene B"]
        # The scene break became an inserted 800ms silence.
        assert 800 in silences
