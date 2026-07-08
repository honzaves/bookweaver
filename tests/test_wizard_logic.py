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
