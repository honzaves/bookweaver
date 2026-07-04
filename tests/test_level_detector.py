from unittest.mock import patch, MagicMock

import pytest

import level_detector


class TestImportGate:
    def test_module_exposes_gate_flags(self):
        assert hasattr(level_detector, "PROFILER_AVAILABLE")
        assert hasattr(level_detector, "PROFILER_IMPORT_ERROR")
        assert isinstance(level_detector.PROFILER_AVAILABLE, bool)

    def test_spacy_model_name_constant(self):
        assert level_detector.SPACY_MODEL == "es_core_news_sm"


class TestBandFromMetrics:
    def _m(self, sent, rare, subj):
        return {
            "mean_sentence_len": sent,
            "rare_word_pct": rare,
            "subjunctive_ratio": subj,
        }

    def test_simple_text_is_b1(self):
        assert level_detector.band_from_metrics(self._m(10.0, 3.0, 0.0)) == "B1"

    def test_moderate_text_is_b2(self):
        assert level_detector.band_from_metrics(self._m(16.0, 8.0, 1.5)) == "B2"

    def test_subjunctive_pushes_to_c1(self):
        # short sentences + low rare%, but subjunctive present → at least C1
        assert level_detector.band_from_metrics(self._m(10.0, 3.0, 4.0)) == "C1"

    def test_rich_text_is_c2(self):
        assert level_detector.band_from_metrics(self._m(30.0, 25.0, 8.0)) == "C2"

    def test_returns_most_advanced_axis(self):
        # long sentences alone (C1 band on length) outrank simple vocab
        assert level_detector.band_from_metrics(self._m(24.0, 2.0, 0.0)) == "C1"


class TestProfileText:
    @pytest.fixture(scope="class")
    def nlp_available(self):
        spacy = pytest.importorskip("spacy")
        if not spacy.util.is_package(level_detector.SPACY_MODEL):
            pytest.skip(f"{level_detector.SPACY_MODEL} not installed")
        pytest.importorskip("wordfreq")

    def test_simple_text_profiles_low(self, nlp_available):
        text = "El niño come pan. La casa es grande. El perro corre."
        result = level_detector.profile_text(text)
        assert result["subjunctive_ratio"] == 0.0
        assert result["band"] in ("B1", "B2")
        assert result["n_words"] > 0

    def test_subjunctive_is_detected(self, nlp_available):
        text = "Quiero que vengas pronto para que hablemos del asunto."
        result = level_detector.profile_text(text)
        assert result["subjunctive_ratio"] > 0.0

    def test_empty_text_is_safe(self, nlp_available):
        result = level_detector.profile_text("")
        assert result["n_words"] == 0
        assert result["band"] in ("B1", "B2", "C1", "C2")


class TestJudge:
    def test_build_judge_prompt_mentions_level(self):
        p = level_detector.build_judge_prompt("Hola mundo.", "B1")
        assert "B1" in p
        assert "Hola mundo." in p

    def test_judge_parses_cefr_token(self):
        fake = MagicMock()
        fake.json.return_value = {"response": "Assessed level: C1. The text uses subjunctive."}
        fake.raise_for_status.return_value = None
        client = MagicMock()
        client.__enter__.return_value.post.return_value = fake
        with patch("httpx.Client", return_value=client):
            result = level_detector.judge_level("texto", "B2", "fakemodel")
        assert result["verdict"] == "C1"

    def test_judge_handles_error_gracefully(self):
        with patch("httpx.Client", side_effect=RuntimeError("boom")):
            result = level_detector.judge_level("texto", "B2", "fakemodel")
        assert result["verdict"] == "?"


class TestAssessAndReport:
    def test_thirds_split_and_report(self, monkeypatch):
        # Stub profile_text so we don't need the real model here.
        monkeypatch.setattr(
            level_detector, "PROFILER_AVAILABLE", True
        )
        monkeypatch.setattr(
            level_detector, "profile_text",
            lambda t: {"mean_sentence_len": 10.0, "rare_word_pct": 4.0,
                       "subjunctive_ratio": 0.0, "band": "B1", "n_words": len(t.split())},
        )
        text = " ".join(["palabra"] * 300)
        result = level_detector.assess_document(
            text, "B1", model=None, run_llm=False
        )
        assert result["whole"]["band"] == "B1"
        assert result["first_third"] is not None
        assert result["last_third"] is not None
        assert result["judge"] is None
        report = level_detector.format_report(result, "B1")
        assert "B1" in report
        assert "last third" in report.lower()

    def test_assess_without_profiler(self, monkeypatch):
        monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", False)
        result = level_detector.assess_document("hola", "B1", run_llm=False)
        assert result["whole"] is None
        report = level_detector.format_report(result, "B1")
        assert "profiler unavailable" in report.lower()

    def test_calibrated_band_is_none_when_no_cuts_file(self, monkeypatch):
        """assess_document must NOT label the profiler band as calibrated.

        When load_cuts() returns None (no cefr_cuts.json / textstat absent),
        calibrated_band must be None so format_report never prints the
        misleading 'readability-based, primary' line."""
        monkeypatch.setattr(level_detector, "load_cuts", lambda: None)
        monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", True)
        monkeypatch.setattr(
            level_detector, "profile_text",
            lambda t: {"mean_sentence_len": 10.0, "rare_word_pct": 4.0,
                       "subjunctive_ratio": 0.0, "band": "B1",
                       "n_words": len(t.split())},
        )
        result = level_detector.assess_document(
            " ".join(["palabra"] * 50), "B1", run_llm=False
        )
        assert result["calibrated_band"] is None, (
            "calibrated_band should be None when no cuts file is present; "
            f"got {result['calibrated_band']!r}"
        )
        report = level_detector.format_report(result, "B1")
        assert "Calibrated band" not in report, (
            "format_report must not print 'Calibrated band' when calibrated_band is None"
        )

    def test_calibrated_band_set_from_readability(self, monkeypatch):
        """assess_document exposes calibrated_band when readability_band succeeds."""
        fake_cuts = {"formula": "fernandez_huerta",
                     "thresholds": [[60.0, "C1"]], "above": "B2"}
        monkeypatch.setattr(level_detector, "load_cuts", lambda: fake_cuts)
        monkeypatch.setattr(level_detector, "readability_band",
                            lambda t, c: "B2")
        monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", False)
        result = level_detector.assess_document("hola", "B1", run_llm=False)
        assert result["calibrated_band"] == "B2", (
            f"expected 'B2', got {result['calibrated_band']!r}"
        )
        report = level_detector.format_report(result, "B1")
        assert "Calibrated band: B2" in report, (
            "format_report must include 'Calibrated band: B2' when calibrated_band is set"
        )


class TestBandDistance:
    def test_one_above_is_distance_one(self):
        assert level_detector.band_distance("B2", "B1") == 1
        assert level_detector.band_distance("C1", "B2") == 1

    def test_two_above_is_distance_two(self):
        assert level_detector.band_distance("C1", "B1") == 2
        assert level_detector.band_distance("C2", "B2") == 2

    def test_below_target_is_negative(self):
        assert level_detector.band_distance("B1", "B2") == -1

    def test_equal_is_zero(self):
        assert level_detector.band_distance("B2", "B2") == 0

    def test_unknown_band_is_zero(self):
        assert level_detector.band_distance("?", "B1") == 0
        assert level_detector.band_distance("A2", "B1") == 0


class TestTextstatReadability:
    def test_textstat_readability_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(level_detector, "TEXTSTAT_AVAILABLE", False)
        assert level_detector.textstat_readability("Hola mundo.") is None

    def test_textstat_readability_returns_float_when_available(self, monkeypatch):
        monkeypatch.setattr(level_detector, "TEXTSTAT_AVAILABLE", True)
        fake = type("T", (), {"set_lang": staticmethod(lambda l: None),
                              "fernandez_huerta": staticmethod(lambda t: 72.34)})
        monkeypatch.setitem(__import__("sys").modules, "textstat", fake)
        assert level_detector.textstat_readability("Hola mundo.") == 72.3


CUTS = {"formula": "fernandez_huerta",
        "thresholds": [[40.0, "C2"], [60.0, "C1"], [80.0, "B2"]],
        "above": "B1"}


class TestReadabilityBand:
    def test_readability_band_maps_scores(self, monkeypatch):
        monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 50.0)
        assert level_detector.readability_band("x", CUTS) == "C1"
        monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 95.0)
        assert level_detector.readability_band("x", CUTS) == "B1"
        monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 30.0)
        assert level_detector.readability_band("x", CUTS) == "C2"

    def test_readability_band_none_without_textstat(self, monkeypatch):
        monkeypatch.setattr(level_detector, "textstat_readability", lambda t: None)
        assert level_detector.readability_band("x", CUTS) is None

    def test_load_cuts_missing_file_returns_none(self):
        assert level_detector.load_cuts("does_not_exist_xyz.json") is None


class TestDocumentBand:
    def test_document_band_prefers_calibrated(self, monkeypatch):
        monkeypatch.setattr(level_detector, "readability_band", lambda t, c: "B2")
        assert level_detector.document_band("x", CUTS) == "B2"

    def test_document_band_falls_back_to_profiler(self, monkeypatch):
        monkeypatch.setattr(level_detector, "readability_band", lambda t, c: None)
        monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", True)
        monkeypatch.setattr(level_detector, "profile_text", lambda t: {"band": "C1"})
        assert level_detector.document_band("x", None) == "C1"

    def test_document_band_none_when_nothing_available(self, monkeypatch):
        monkeypatch.setattr(level_detector, "readability_band", lambda t, c: None)
        monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", False)
        assert level_detector.document_band("x", None) is None
