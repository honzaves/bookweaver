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

import re

SPACY_MODEL = "es_core_news_sm"

PROFILER_AVAILABLE = False
PROFILER_IMPORT_ERROR: str | None = None

try:
    import spacy  # noqa: F401
    import wordfreq  # noqa: F401
    PROFILER_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - exercised via stubs
    PROFILER_IMPORT_ERROR = str(exc)

TEXTSTAT_AVAILABLE = False
try:
    import textstat  # noqa: F401
    TEXTSTAT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatch
    pass


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


# Ordered CEFR bands the profiler can emit; index gives an ordinal so the
# worker can measure how far a chunk's level sits above its target.
BAND_ORDER: list[str] = ["B1", "B2", "C1", "C2"]


def band_distance(detected: str, target: str) -> int:
    """Signed distance of *detected* above *target* on BAND_ORDER.

    Positive => harder than target (candidate for regeneration); negative =>
    easier; 0 => equal or a band not in BAND_ORDER (never regenerate on a band
    we cannot place)."""
    if detected not in BAND_ORDER or target not in BAND_ORDER:
        return 0
    return BAND_ORDER.index(detected) - BAND_ORDER.index(target)


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


def textstat_readability(text: str) -> float | None:
    """Raw Fernández-Huerta readability ease for Spanish *text* (higher =
    easier). Returns None when textstat is unavailable. Uncalibrated — for
    advisory logging and drift-spotting only, never a gate."""
    if not TEXTSTAT_AVAILABLE:
        return None
    import textstat
    textstat.set_lang("es")
    return round(textstat.fernandez_huerta(text), 1)


# ──────────────────────────────────────────────────────────────
#  OLLAMA HELPER + LLM JUDGE
# ──────────────────────────────────────────────────────────────
_CEFR_RE = re.compile(r"\b([ABC][12])\b")


def ollama_generate(model: str, prompt: str, timeout: int = 1200) -> str | None:
    """Send *prompt* to the local Ollama instance and return the response
    text, or None on any error. Standalone twin of worker._ollama_call so
    the CLI does not depend on the QThread worker."""
    try:
        import httpx
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
            )
            response.raise_for_status()
            return response.json().get("response", "").strip() or None
    except Exception:
        return None


def build_judge_prompt(text: str, target_level: str) -> str:
    """Prompt asking the model to assess the CEFR level of *text*."""
    return (
        "You are a CEFR assessment expert for Spanish. Read the passage and "
        "judge the single CEFR level that best describes its difficulty.\n\n"
        "RULES:\n"
        "- Choose exactly one of: A1, A2, B1, B2, C1, C2.\n"
        "- Base the judgement on vocabulary frequency, grammatical complexity "
        "(especially subjunctive/conditional use), and sentence length.\n"
        f"- The text was generated targeting CEFR {target_level}; say whether "
        "it meets, falls below, or exceeds that target.\n"
        "- Begin your reply with 'Assessed level: <LEVEL>' on its own line, "
        "then one or two sentences of justification.\n\n"
        f"PASSAGE:\n{text}\n"
    )


def judge_level(
    text: str, target_level: str, model: str, timeout: int = 1200
) -> dict:
    """Ask the local Ollama model to assess *text*'s CEFR level."""
    raw = ollama_generate(model, build_judge_prompt(text, target_level), timeout)
    if not raw:
        return {"verdict": "?", "raw": ""}
    match = _CEFR_RE.search(raw)
    return {"verdict": match.group(1) if match else "?", "raw": raw}


# ──────────────────────────────────────────────────────────────
#  DOCUMENT ASSESSMENT + REPORT
# ──────────────────────────────────────────────────────────────
def _third(words: list[str], which: str) -> str:
    n = len(words)
    if n == 0:
        return ""
    cut = max(1, n // 3)
    return " ".join(words[:cut] if which == "first" else words[-cut:])


def assess_document(
    text: str,
    target_level: str,
    model: str | None = None,
    timeout: int = 1200,
    run_llm: bool = True,
) -> dict:
    """Profile the whole text plus its first/last third (drift), and
    optionally run the LLM-judge. Profiler keys are None when unavailable."""
    out: dict = {"whole": None, "first_third": None, "last_third": None,
                 "judge": None}
    if PROFILER_AVAILABLE:
        words = text.split()
        out["whole"] = profile_text(text)
        out["first_third"] = profile_text(_third(words, "first"))
        out["last_third"] = profile_text(_third(words, "last"))
    if run_llm and model:
        out["judge"] = judge_level(text, target_level, model, timeout)
    return out


def format_report(assessment: dict, target_level: str) -> str:
    """Render *assessment* as a human-readable multi-line report."""
    lines = [f"CEFR assessment (target: {target_level})", "-" * 40]
    whole = assessment["whole"]
    if whole is None:
        lines.append("Feature profiler unavailable (spaCy/wordfreq not "
                     "installed) — install spacy, wordfreq and the "
                     "es_core_news_sm wheel to enable it.")
    else:
        lines.append(
            f"Whole document:  band={whole['band']}  "
            f"sent_len={whole['mean_sentence_len']}  "
            f"rare%={whole['rare_word_pct']}  "
            f"subj%={whole['subjunctive_ratio']}  "
            f"({whole['n_words']} words)"
        )
        ft, lt = assessment["first_third"], assessment["last_third"]
        lines.append(f"First third:     band={ft['band']}  "
                     f"sent_len={ft['mean_sentence_len']}")
        lines.append(f"Last third:      band={lt['band']}  "
                     f"sent_len={lt['mean_sentence_len']}")
        if ft["band"] != lt["band"]:
            lines.append(f"⚠️  Drift: level shifts {ft['band']} → {lt['band']} "
                         "between first and last third.")
    judge = assessment["judge"]
    if judge:
        lines.append(f"LLM judge:       {judge['verdict']}")
        if judge["raw"]:
            lines.append(f"  ↳ {judge['raw'].splitlines()[0]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from settings import OLLAMA_TIMEOUT

    parser = argparse.ArgumentParser(
        description="Assess the CEFR level of a Spanish text file."
    )
    parser.add_argument("file", help="Path to a .txt file to assess.")
    parser.add_argument("--level", default="B2",
                        help="Target CEFR level (default B2).")
    parser.add_argument("--model", default=None,
                        help="Ollama model for the LLM-judge. Omit to skip it.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip the LLM-judge; run the profiler only.")
    parser.add_argument("--timeout", type=int, default=OLLAMA_TIMEOUT,
                        help="Ollama call timeout in seconds.")
    args = parser.parse_args(argv)

    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()
    assessment = assess_document(
        text, args.level, model=args.model, timeout=args.timeout,
        run_llm=not args.no_llm,
    )
    print(format_report(assessment, args.level))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
