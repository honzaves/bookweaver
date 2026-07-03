import level_detector


class TestImportGate:
    def test_module_exposes_gate_flags(self):
        assert hasattr(level_detector, "PROFILER_AVAILABLE")
        assert hasattr(level_detector, "PROFILER_IMPORT_ERROR")
        assert isinstance(level_detector.PROFILER_AVAILABLE, bool)

    def test_spacy_model_name_constant(self):
        assert level_detector.SPACY_MODEL == "es_core_news_sm"
