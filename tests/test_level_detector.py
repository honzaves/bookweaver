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
