"""
level_detector.py
-----------------
Qt-free CEFR level assessment for BookWeaver's Spanish output.

Two independent assessors over a block of text:
  - profile_text()  — deterministic feature profiler (spaCy + wordfreq)
  - judge_level()   — local Ollama LLM-judge

Heavy deps (spacy, es_core_news_sm, wordfreq) sit behind an import gate;
the module imports and the LLM-judge work without them. Never imports Qt,
app, worker, or widgets.
"""
from __future__ import annotations

SPACY_MODEL = "es_core_news_sm"

PROFILER_AVAILABLE = False
PROFILER_IMPORT_ERROR: str | None = None

try:
    import spacy  # noqa: F401
    import wordfreq  # noqa: F401
    PROFILER_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised via stubs
    PROFILER_IMPORT_ERROR = str(exc)
