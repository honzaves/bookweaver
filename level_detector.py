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


# ──────────────────────────────────────────────────────────────
#  DETERMINISTIC BANDING  (starting thresholds — tunable)
# ──────────────────────────────────────────────────────────────
# Each row is the UPPER bound for that band on every axis. A text is
# placed in the LOWEST band whose every axis is within bounds; if it
# exceeds B1/B2/C1 on any axis it spills up. The most-advanced axis wins,
# which is why subjunctive use alone lifts an otherwise-simple text.
CEFR_THRESHOLDS: list[tuple[str, float, float, float]] = [
    # band, max_sentence_len, max_rare_pct, max_subjunctive_ratio
    ("B1", 12.0, 5.0, 1.0),
    ("B2", 18.0, 10.0, 3.0),
    ("C1", 25.0, 18.0, 100.0),
]


def band_from_metrics(metrics: dict) -> str:
    """Map a feature-metrics dict to a CEFR band B1/B2/C1/C2.

    metrics keys: mean_sentence_len, rare_word_pct, subjunctive_ratio.
    Thresholds are deliberately conservative starting points; tune against
    real graded output."""
    sent = metrics["mean_sentence_len"]
    rare = metrics["rare_word_pct"]
    subj = metrics["subjunctive_ratio"]
    for band, max_sent, max_rare, max_subj in CEFR_THRESHOLDS:
        if sent <= max_sent and rare <= max_rare and subj <= max_subj:
            return band
    return "C2"
