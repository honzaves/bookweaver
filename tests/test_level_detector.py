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
