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


# ──────────────────────────────────────────────────────────────
#  FEATURE PROFILER  (requires spaCy + wordfreq)
# ──────────────────────────────────────────────────────────────
# wordfreq Zipf scale: < 3.5 ≈ below "fairly common". Note: frequency is
# looked up on the *surface* form (the lemmatizer is excluded for speed), so
# inflected Spanish forms score slightly rarer than their lemmas — rare_word_pct
# therefore runs a little hot. This is an accepted, tunable approximation.
RARE_ZIPF_CUTOFF = 3.5

_NLP = None


def _load_nlp():
    """Load and cache the Spanish spaCy pipeline. Excludes the parser, NER,
    and lemmatizer — the dependency parser is memory-heavy on whole-book
    texts (on the order of 1 GB per 100k chars) and only sentence boundaries
    are needed, which the cheap rule-based sentencizer provides. The
    morphologizer stays: it supplies the Mood=Sub feature the profiler
    counts."""
    global _NLP
    if _NLP is None:
        import spacy
        _NLP = spacy.load(SPACY_MODEL, exclude=["parser", "ner", "lemmatizer"])
        if "sentencizer" not in _NLP.pipe_names:
            _NLP.add_pipe("sentencizer")
    return _NLP


def profile_text(text: str) -> dict:
    """Return deterministic CEFR features for *text* (Spanish)."""
    from wordfreq import zipf_frequency

    nlp = _load_nlp()
    # Large books can exceed spaCy's default 1,000,000-char ceiling; raise it
    # for this call so big concatenated outputs still profile (safe now that
    # the memory-heavy parser is excluded in _load_nlp).
    nlp.max_length = max(nlp.max_length, len(text) + 1)
    doc = nlp(text)

    sentences = [s for s in doc.sents if s.text.strip()]
    content = [t for t in doc if t.is_alpha]
    n_words = len(content)

    verbs = [t for t in doc if t.pos_ in ("VERB", "AUX")]
    subj_verbs = [t for t in verbs if "Mood=Sub" in str(t.morph)]
    rare = [
        t for t in content
        if zipf_frequency(t.text.lower(), "es") < RARE_ZIPF_CUTOFF
    ]

    mean_sentence_len = (n_words / len(sentences)) if sentences else 0.0
    rare_word_pct = (100.0 * len(rare) / n_words) if n_words else 0.0
    subjunctive_ratio = (100.0 * len(subj_verbs) / len(verbs)) if verbs else 0.0

    metrics = {
        "mean_sentence_len": round(mean_sentence_len, 2),
        "rare_word_pct": round(rare_word_pct, 2),
        "subjunctive_ratio": round(subjunctive_ratio, 2),
    }
    metrics["band"] = band_from_metrics(metrics)
    metrics["n_words"] = n_words
    return metrics
