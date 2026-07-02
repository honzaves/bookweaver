# Language-Level Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tool that assesses the CEFR language level of BookWeaver's Spanish output, available as a standalone CLI and as an optional in-app check with two modes: a log-only **end-of-book report**, or **per-chunk validation** that regenerates any chunk whose level runs 2+ CEFR bands above target.

**Architecture:** A new Qt-free module `level_detector.py` provides two independent assessors over a block of Spanish text — a deterministic **feature profiler** (spaCy lemmatisation + morphology + `wordfreq` lexical frequency) and a local **Ollama LLM-judge** — plus a small standalone Ollama HTTP helper they share, and a pure `band_distance()` gate over the ordered bands. Heavy deps (`spacy`, the Spanish model, `wordfreq`) sit behind an import gate exactly like `tts.py`. A CLI `main()` runs both over a `.txt` file. In-app, the user picks one of three options via a radio (`level_check` = `"off"` / `"report"` / `"validate"`):

- **`"report"`** — `worker.py` runs `assess_document` + `format_report` as an optional, log-only, post-loop step that never fails the run (the original design).
- **`"validate"`** — additionally, inside the chunk loop, each Spanish-producing chunk is profiled and, when its band is 2+ levels above the target, regenerated (up to 2 retries) with a stricter "simplify harder" prompt. Gated entirely on the fast deterministic profiler (no extra LLM call to assess); the only extra LLM cost is an actual regeneration. The end-of-book report still runs afterwards.

**Tech Stack:** Python 3, spaCy + `es_core_news_sm`, `wordfreq`, `httpx` (already a dependency), argparse, pytest.

## Global Constraints

- **Max line length 100; PEP 8.** `E221` (aligned assignments) is suppressed. Run `pycodestyle --statistics *.py`.
- **`level_detector.py` must be Qt-free** and must not import `app`, `worker`, or `widgets`. It may import `settings` for `OLLAMA_TIMEOUT` only.
- **Optional heavy deps are import-gated** behind `PROFILER_AVAILABLE` / `PROFILER_IMPORT_ERROR`, mirroring `tts.py`'s `TTS_AVAILABLE` pattern. The test suite must pass with these deps absent.
- **The `"report"` path is post-loop, log-only, lazy-imported, and never fails the run** — mirror the existing TTS and book-key-ideas post-loop blocks in `worker.py`.
- **The `"validate"` path must also never fail the run.** If the profiler is unavailable (`PROFILER_AVAILABLE` is False), if the output is English, or if a chunk is below the word floor, validation is silently skipped with a single log line — the run proceeds with un-validated output exactly as today. Regeneration is **within-step**: it does not change `total_steps` or progress accounting, it only makes a step take longer. The retry loop must honor `self._abort` between attempts.
- **Worker must never import Qt UI classes.** Communication is via existing `pyqtSignal`s only.
- Install deps with `uv pip install` (not `uv sync`). The spaCy model installs via a **pinned wheel URL**, not `python -m spacy download` (which does not respect the uv venv).
- Known pre-existing test failure to ignore (do **not** "fix"): `tests/test_settings.py::TestOllamaTimeout::test_defaults_when_missing`.
- After any `worker.py` edit touching a class boundary, run `grep -n "^class " *.py` and confirm the expected classes are still present (see CLAUDE.md "Known historical issues").
- **Coordination with the sliding-window plan:** these two plans are independently *designed* but not independently *mergeable* — both append a key to the same `_build_config()` dict literal, both add a row to `_add_options_group()`, both edit `worker.py` `run()`, `tests/test_worker.py`, and `CLAUDE.md`. The `"validate"` path (Tasks 8–10) widens this overlap further: it also edits `prompts.py` (`build_rewrite_prompt`/`build_translation_prompt` signatures), `tests/test_prompts.py`, and the **inside** of `worker.py`'s chunk loop (the three Spanish-producing sites). Implement the two plans **sequentially**; the second one rebases on the first and expects those shared spots to already have the other feature's line. Two spots need explicit reconciliation when this plan runs **second**: (a) both plans add a trailing default parameter to `build_rewrite_prompt`/`build_translation_prompt` and each calls its own "the last parameter" — the order of `simplify_note`/`context_block` does not matter, but always pass both by keyword; (b) if the sliding-window plan landed first, the three Spanish-producing call sites already pass `context_block=context_block` — carry that argument into the `build_fn` closures Task 10 introduces (in the closure's builder call **and** the non-validate direct call), otherwise validate-mode runs would silently lose the continuity carry.

---

### Task 1: Module skeleton + import gate

**Files:**
- Create: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Produces: module-level `PROFILER_AVAILABLE: bool`, `PROFILER_IMPORT_ERROR: str | None`, and constant `SPACY_MODEL = "es_core_news_sm"`.

- [ ] **Step 1: Do NOT stub spaCy/wordfreq in conftest**

Deliberately add **no** stub. The import gate (Step 4) makes `level_detector` import cleanly when the deps are absent, so no stub is needed — and a `MagicMock` stub would be actively harmful: it is importable, so `pytest.importorskip("spacy")` in Task 3 would return the mock instead of skipping, and the profiler tests would run against mocks (`n_words == 0`) and fail. With no stub, `PROFILER_AVAILABLE` is correctly `False` deps-absent and Task 3's tests skip cleanly. (`test_tts.py` already proves the suite runs with its optional deps genuinely absent — follow that, not a mock.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_level_detector.py
import level_detector


class TestImportGate:
    def test_module_exposes_gate_flags(self):
        assert hasattr(level_detector, "PROFILER_AVAILABLE")
        assert hasattr(level_detector, "PROFILER_IMPORT_ERROR")
        assert isinstance(level_detector.PROFILER_AVAILABLE, bool)

    def test_spacy_model_name_constant(self):
        assert level_detector.SPACY_MODEL == "es_core_news_sm"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'level_detector'`

- [ ] **Step 4: Write minimal implementation**

```python
# level_detector.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_level_detector.py -v`
Expected: PASS

Note: `PROFILER_AVAILABLE` reflects reality — `True` only when spaCy and wordfreq are actually installed, `False` otherwise. Tests needing *real* spaCy use `pytest.importorskip` and skip when absent (Task 3).

- [ ] **Step 6: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: level_detector module skeleton with import gate"
```

---

### Task 2: Pure band-mapping from a metrics dict

This is the deterministic CEFR decision, kept pure (no spaCy) so it is fully testable without the model. Feature extraction (Task 3) produces the metrics dict; this maps it to a band.

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Produces: `band_from_metrics(metrics: dict) -> str` returning one of `"B1"`, `"B2"`, `"C1"`, `"C2"`. `metrics` keys: `mean_sentence_len: float`, `rare_word_pct: float`, `subjunctive_ratio: float`.
- Produces: `CEFR_THRESHOLDS: list[tuple[str, float, float, float]]` — `(band, max_sentence_len, max_rare_pct, max_subjunctive_ratio)`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::TestBandFromMetrics -v`
Expected: FAIL with `AttributeError: module 'level_detector' has no attribute 'band_from_metrics'`

- [ ] **Step 3: Write minimal implementation**

Append to `level_detector.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_level_detector.py::TestBandFromMetrics -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: pure CEFR band-from-metrics mapping"
```

---

### Task 3: Feature extraction (spaCy + wordfreq)

Turns raw Spanish text into the metrics dict Task 2 consumes. Requires real spaCy + model, so its tests use `importorskip` and a real model load.

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Consumes: `band_from_metrics` (Task 2), `SPACY_MODEL` (Task 1).
- Produces: `profile_text(text: str) -> dict` returning `{"mean_sentence_len": float, "rare_word_pct": float, "subjunctive_ratio": float, "band": str, "n_words": int}`.
- Produces: `_load_nlp()` (cached spaCy pipeline loader) and `RARE_ZIPF_CUTOFF = 3.5`.

- [ ] **Step 1: Write the failing test (skips when the real model is absent)**

```python
import pytest


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
```

- [ ] **Step 2: Run test to verify it fails or skips**

Run: `pytest tests/test_level_detector.py::TestProfileText -v`
Expected: FAIL with `AttributeError: ... no attribute 'profile_text'` (or SKIP if the model is not installed — install it per Task 6 to actually exercise these).

- [ ] **Step 3: Write minimal implementation**

Append to `level_detector.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes (model must be installed)**

Run: `pytest tests/test_level_detector.py::TestProfileText -v`
Expected: PASS (or SKIP if the model is not installed; CI without the model will skip).

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: spaCy+wordfreq feature profiler"
```

---

### Task 4: Standalone Ollama helper + LLM-judge

A self-contained HTTP call (the worker's `_ollama_call` is a `QThread` method the CLI can't use) plus the CEFR judge built on it.

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ollama_generate(model: str, prompt: str, timeout: int = 1200) -> str | None`.
- Produces: `build_judge_prompt(text: str, target_level: str) -> str`.
- Produces: `judge_level(text: str, target_level: str, model: str, timeout: int = 1200) -> dict` returning `{"verdict": str, "raw": str}` where `verdict` is the first CEFR token found (`"B1".."C2"`) or `"?"`.

- [ ] **Step 1: Write the failing test (httpx mocked — no network)**

```python
from unittest.mock import patch, MagicMock


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::TestJudge -v`
Expected: FAIL with `AttributeError: ... no attribute 'build_judge_prompt'`

- [ ] **Step 3: Write minimal implementation**

Add `import re` to the module's **top** import block (a mid-file module-level
import would trip pycodestyle E402), then append to `level_detector.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_level_detector.py::TestJudge -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: standalone ollama helper + CEFR LLM-judge"
```

---

### Task 5: Position-aware drift report + CLI

Profiles the whole text plus its first and last thirds (to surface end-of-generation drift), runs the judge, and prints a report. Exposed as `python level_detector.py <file> ...`.

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Consumes: `profile_text`, `judge_level`, `PROFILER_AVAILABLE`.
- Produces: `assess_document(text, target_level, model=None, timeout=1200, run_llm=True) -> dict` with keys `whole`, `first_third`, `last_third` (each a metrics dict or `None` when the profiler is unavailable), and `judge` (a judge dict or `None`).
- Produces: `format_report(assessment: dict, target_level: str) -> str`.
- Produces: `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::TestAssessAndReport -v`
Expected: FAIL with `AttributeError: ... no attribute 'assess_document'`

- [ ] **Step 3: Write minimal implementation**

Append to `level_detector.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_level_detector.py::TestAssessAndReport -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: drift-aware assessment + CLI for level_detector"
```

---

### Task 6: Install deps and smoke-test the CLI

Documentation + manual verification task. No automated test; this proves the real toolchain works end to end.

**Files:**
- Modify: `CLAUDE.md` (add a short "Language-level detector" section + dep install note)

- [ ] **Step 1: Install the profiler dependencies**

```bash
uv pip install spacy wordfreq
# Install the Spanish model as a pinned wheel (NOT `python -m spacy download`,
# which does not respect the uv venv). Match the version to the installed spaCy
# major.minor; check with: python -c "import spacy; print(spacy.__version__)"
uv pip install \
  "https://github.com/explosion/spacy-models/releases/download/es_core_news_sm-3.7.0/es_core_news_sm-3.7.0-py3-none-any.whl"
```

If the installed spaCy is not 3.7.x, substitute the matching model release tag from
https://github.com/explosion/spacy-models/releases (search `es_core_news_sm`).

- [ ] **Step 2: Run the profiler-only path against a real output file**

```bash
python level_detector.py path/to/some_output_ES_B1.txt --level B1 --no-llm
```

Expected: a report printing `band=`, `sent_len=`, `rare%=`, `subj%=` for whole/first/last third, and a drift line if first and last thirds differ.

- [ ] **Step 3: Run the full path including the LLM-judge**

```bash
python level_detector.py path/to/some_output_ES_B1.txt --level B1 --model <your-loaded-ollama-model>
```

Expected: the profiler report plus an `LLM judge: <LEVEL>` line. Confirms the standalone Ollama call reaches your local instance.

- [ ] **Step 4: Run the full suite (skips model-dependent tests if absent)**

Run: `pytest -q`
Expected: PASS except the one known pre-existing failure
`tests/test_settings.py::TestOllamaTimeout::test_defaults_when_missing`.

- [ ] **Step 5: Document and commit**

Add to `CLAUDE.md` under a new "Language-level detector" subsection: the module's purpose, the gated deps + the pinned-wheel install note, the CLI invocation, and that the in-app check is post-loop/log-only (Task 7). Then:

```bash
git add CLAUDE.md
git commit -m "docs: document language-level detector + install"
```

---

### Task 7: In-app level check — radio UI + end-of-book report

A 3-way radio (Off / Report / Validate) that selects the in-app level check. This
task builds the radio and the **`"report"`** path: after the run completes,
profile+judge the assembled output and log the result. Mirrors the existing
post-loop TTS/book-key-ideas pattern: lazy-imported, log-only, never fails the
run. The **`"validate"`** path is added in Task 10 and reuses this same radio and
config key; `"validate"` also runs this report at the end, so the post-loop block
fires for both `"report"` and `"validate"`.

**Files:**
- Modify: `app.py` (radio group in `_add_options_group`; `level_check` string in `_build_config`; passthrough in `_on_resume`)
- Modify: `worker.py` (post-loop block in `run()` after output is written)
- Test: `tests/test_worker.py` (the post-loop helper)

**Interfaces:**
- Consumes: `level_detector.assess_document`, `level_detector.format_report` (Task 5).
- Produces: config key `level_check: str` — one of `"off"`, `"report"`, `"validate"`.
- Produces: `ProcessingWorker._run_level_check(results, target_level, model)` — log-only, never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py — new class
from unittest.mock import MagicMock, patch
from worker import ProcessingWorker


class TestLevelCheck:
    def _worker(self):
        w = ProcessingWorker.__new__(ProcessingWorker)  # bypass QThread init
        w.log = MagicMock()
        w._timeout = 1200
        return w

    def test_level_check_logs_report(self):
        w = self._worker()
        results = [("Capítulo 1", "Hola mundo."), ("Capítulo 2", "Adiós.")]
        with patch("level_detector.assess_document",
                   return_value={"whole": None, "first_third": None,
                                 "last_third": None, "judge": None}) as ad, \
             patch("level_detector.format_report", return_value="REPORT"):
            w._run_level_check(results, "B1", "fakemodel")
        ad.assert_called_once()
        # the report text reached the log
        logged = " ".join(str(c.args[0]) for c in w.log.emit.call_args_list)
        assert "REPORT" in logged

    def test_level_check_never_raises(self):
        w = self._worker()
        with patch("level_detector.assess_document",
                   side_effect=RuntimeError("boom")):
            w._run_level_check([("t", "b")], "B1", "fakemodel")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::TestLevelCheck -v`
Expected: FAIL with `AttributeError: 'ProcessingWorker' object has no attribute '_run_level_check'`

- [ ] **Step 3: Add the worker helper**

In `worker.py`, add this method to `ProcessingWorker` (place it just before `_generate_mp3`):

```python
    # ── post-run language-level check (optional, log-only) ────
    def _run_level_check(
        self,
        results: list[tuple[str, str]],
        target_level: str,
        model: str,
    ) -> None:
        """Assess the assembled output's CEFR level and log a report.
        Never raises — a failure here must not undo written output."""
        try:
            import level_detector
        except ImportError as exc:
            self.log.emit(f"Level check skipped (import failed: {exc}).", "warning")
            return
        body = "\n\n".join(body for _, body in results)
        self.log.emit("\n🔎  Assessing output language level…", "info")
        try:
            assessment = level_detector.assess_document(
                body, target_level, model=model, timeout=self._timeout,
                run_llm=True,
            )
            for line in level_detector.format_report(
                assessment, target_level
            ).splitlines():
                self.log.emit(f"   {line}", "muted")
        except Exception as exc:
            self.log.emit(f"Level check failed: {exc}", "warning")
```

- [ ] **Step 4: Call it post-loop in `run()`**

In `worker.py` `run()`, immediately after the MP3 block (after the `if cfg.get("generate_mp3")...` block, before `self.finished.emit(True, ...)`), add. The profiler and judge are Spanish-only, so skip when the output is English (`summarise_only`, or `summarise_key_ideas` with `summary_lang == "en"`):

```python
        # ── end-of-book language-level report (log-only, Spanish output only) ──
        # Runs for both "report" and "validate"; "validate" additionally
        # regenerated chunks inline during the loop (Task 10).
        if cfg.get("level_check") in ("report", "validate"):
            output_is_english = mode == "summarise_only" or (
                mode == "summarise_key_ideas" and summary_lang == "en"
            )
            if output_is_english:
                self.log.emit(
                    "🔎  Level check skipped — it is Spanish-only and this "
                    "output is English.",
                    "muted",
                )
            else:
                self._run_level_check(results, level, model)
```

- [ ] **Step 5: Add the UI radio + config field**

In `app.py` `_add_options_group`, after the MP3 voice row block (after
`self._update_mp3_checkbox_state()`), add a 3-way radio. Use `QRadioButton`s in a
`QButtonGroup` so they are mutually exclusive; default to Off. The **Validate**
option requires the spaCy profiler, so grey it out when spaCy is absent — check
cheaply with `importlib.util.find_spec("spacy")` (same precedent app.py already
uses for Kokoro; do **not** import `level_detector` or `spacy` in `app.py`).

```python
        ol.addSpacing(4)
        ol.addWidget(QLabel("Language-level check:"))
        self._level_check_group = QButtonGroup(self)
        self._level_off_radio = QRadioButton("Off")
        self._level_report_radio = QRadioButton("Report level at end of book")
        self._level_validate_radio = QRadioButton(
            "Validate each chunk (regenerate if 2+ levels too hard) + report"
        )
        self._level_off_radio.setChecked(True)
        for rb in (self._level_off_radio, self._level_report_radio,
                   self._level_validate_radio):
            self._level_check_group.addButton(rb)
            ol.addWidget(rb)
        # The validate path needs the spaCy profiler; grey it out if absent.
        if importlib.util.find_spec("spacy") is None:
            self._level_validate_radio.setEnabled(False)
            self._level_validate_radio.setToolTip(
                "Install spaCy + es_core_news_sm to enable per-chunk validation."
            )
```

(`QButtonGroup`, `QRadioButton`, `QLabel` come from `PyQt6.QtWidgets`; add to the
existing import there. `importlib.util` is stdlib — `app.py` already imports it
for the Kokoro check; reuse that import.)

In `_build_config`, add to the returned dict (map radio → string):

```python
            "level_check": (
                "validate" if self._level_validate_radio.isChecked()
                else "report" if self._level_report_radio.isChecked()
                else "off"
            ),
```

In `_on_resume`, the config is rebuilt by spreading `**self._resume_state["config"]`, so `level_check` rides along automatically — no change needed. (Confirm by reading `_on_resume`.)

- [ ] **Step 6: Run tests + class-boundary guard**

Run: `pytest tests/test_worker.py::TestLevelCheck -v` → Expected: PASS
Run: `grep -n "^class " *.py` → Expected: all classes from CLAUDE.md present, including `worker.py: class ProcessingWorker(QThread)`.

- [ ] **Step 7: Commit**

```bash
git add app.py worker.py tests/test_worker.py
git commit -m "feat: in-app level-check radio + end-of-book report"
```

---

### Task 8: Pure band-distance gate

The single decision at the heart of the `"validate"` path — "is this chunk too
hard?" — kept pure (no spaCy, no model) so it is fully testable. Maps two CEFR
bands to a signed ordinal distance; the worker regenerates when the distance is
`>= 2`.

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Produces: `BAND_ORDER: list[str] = ["B1", "B2", "C1", "C2"]`.
- Produces: `band_distance(detected: str, target: str) -> int` — signed
  `BAND_ORDER.index(detected) - BAND_ORDER.index(target)`. Positive means
  *harder* than target. Unknown bands (e.g. `"?"`, `"A2"`, not in `BAND_ORDER`)
  return `0` (treat as "do not regenerate" — never block on a band we cannot place).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::TestBandDistance -v`
Expected: FAIL with `AttributeError: ... no attribute 'band_distance'`

- [ ] **Step 3: Write minimal implementation**

Append to `level_detector.py` (near `CEFR_THRESHOLDS`/`band_from_metrics`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_level_detector.py::TestBandDistance -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: pure band-distance gate for per-chunk validation"
```

---

### Task 9: "Simplify harder" prompt parameter

Gives the two Spanish-producing prompt builders an optional instruction the
worker appends on a regeneration, telling the model its previous output was too
advanced. Pure `prompts.py` change, no Qt, fully unit-testable.

**Files:**
- Modify: `prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Modifies: `build_rewrite_prompt(summary, level, idx, creativity, simplify_note="")`
  and `build_translation_prompt(chunk, level, idx, creativity, simplify_note="")`
  — new trailing keyword-only-style param, default `""` (no behaviour change when
  omitted). When non-empty, the note is appended as an explicit instruction block.
- Produces: `build_simplify_note(detected: str, target: str) -> str` — the
  standard regeneration instruction, e.g. *"Your previous version was assessed at
  C1 but the target is B1. It is too advanced: use more common, everyday words,
  shorter sentences, and avoid the subjunctive where a simpler construction
  works."*

- [ ] **Step 1: Write the failing test**

```python
import prompts


class TestSimplifyNote:
    def test_note_mentions_both_levels(self):
        note = prompts.build_simplify_note("C1", "B1")
        assert "C1" in note and "B1" in note

    def test_rewrite_includes_note_when_passed(self):
        base = prompts.build_rewrite_prompt("resumen", "B1", 0, 5)
        withnote = prompts.build_rewrite_prompt(
            "resumen", "B1", 0, 5, simplify_note="SIMPLIFY-MARKER"
        )
        assert "SIMPLIFY-MARKER" not in base
        assert "SIMPLIFY-MARKER" in withnote

    def test_translation_includes_note_when_passed(self):
        withnote = prompts.build_translation_prompt(
            "texto", "B1", 0, 5, simplify_note="SIMPLIFY-MARKER"
        )
        assert "SIMPLIFY-MARKER" in withnote

    def test_default_omitted_is_unchanged(self):
        # Calling without the new param must not alter existing output.
        a = prompts.build_translation_prompt("texto", "B1", 0, 5)
        b = prompts.build_translation_prompt("texto", "B1", 0, 5, simplify_note="")
        assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompts.py::TestSimplifyNote -v`
Expected: FAIL with `TypeError: build_rewrite_prompt() got an unexpected keyword argument 'simplify_note'` (or `AttributeError` for `build_simplify_note`).

- [ ] **Step 3: Write minimal implementation**

In `prompts.py`:
1. Add `build_simplify_note(detected, target)` returning the instruction string.
2. Add `simplify_note: str = ""` as the last parameter of `build_rewrite_prompt`
   and `build_translation_prompt`. When truthy, append it to the prompt as its
   own clearly-delimited instruction line (place it **after** the level guidance
   so it reads as an override). Keep the default-empty path byte-identical to the
   current output so `test_default_omitted_is_unchanged` holds.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompts.py::TestSimplifyNote -v`
Expected: PASS. Also run the full `tests/test_prompts.py` to confirm no existing
prompt test regressed (the default path must be unchanged).

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: optional simplify-harder note on rewrite/translation prompts"
```

---

### Task 10: Per-chunk validate + regenerate in the worker

Wires the gate (Task 8), the profiler (Task 3), and the simplify note (Task 9)
into the chunk loop. A single helper validates a freshly generated Spanish chunk
and regenerates it up to twice with a stricter prompt. Used at all three
Spanish-producing sites so the loop lives in one place.

**Files:**
- Modify: `worker.py` (`run()` — wrap the three Spanish sites; new helper)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `level_detector.PROFILER_AVAILABLE`, `level_detector.profile_text`,
  `level_detector.band_distance` (Tasks 1/3/8); `prompts.build_simplify_note`
  and the `simplify_note` param (Task 9).
- Produces: `ProcessingWorker._generate_validated_chunk(model, build_fn, target_level, label, temperature, max_retries=2, min_words=150) -> str | None`
  where `build_fn(simplify_note: str) -> str` returns the prompt for an attempt
  (the call site closes over the chunk/summary, level, idx, creativity). Returns
  the accepted text, or `None` on an `_ollama_call` failure (so the existing
  `if result is None:` abort/fail path still applies), exactly like a bare
  `_ollama_call`.

**Behaviour of the helper:**
1. `attempt 0`: `_ollama_call(model, build_fn(""), label=label,
   temperature=temperature)` — `label` and `temperature` are keyword-only on
   `_ollama_call`; pass the prompt positionally (the tests read
   `call_args_list[n].args[1]`). If `None`, return `None` (caller fails the
   chapter as today).
2. If the profiler is unavailable, accept attempt 0 as-is. Otherwise profile
   the attempt **exactly once** — `m = level_detector.profile_text(text)` —
   and reuse `m` for both checks below (the tests' `side_effect` lists assume
   one `profile_text` call per attempt). If `m["n_words"] < min_words`, accept
   as-is (log one muted line for the word-floor skip). No gate.
3. Else `dist = level_detector.band_distance(m["band"], target_level)`. If
   `dist < 2`, accept. Otherwise log a warning and re-call with
   `build_fn(build_simplify_note(m["band"], target_level))`. Repeat up to
   `max_retries`. Between attempts, if `self._abort`, return the best text so
   far.
4. After exhausting retries, keep the **last** generated text, log that the chunk
   could not be brought within range, and return it (never fails the run).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py — new class
from unittest.mock import MagicMock, patch
from worker import ProcessingWorker


class TestValidatedChunk:
    def _worker(self):
        w = ProcessingWorker.__new__(ProcessingWorker)  # bypass QThread init
        w.log = MagicMock()
        w._timeout = 1200
        w._abort = False
        return w

    def test_accepts_when_within_range(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="texto bueno")
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "B2", "n_words": 500}):
            out = w._generate_validated_chunk(
                "m", lambda note: f"PROMPT[{note}]", "B1", "lbl", 0.4
            )
        assert out == "texto bueno"
        w._ollama_call.assert_called_once()  # no regeneration (B2 vs B1 = 1)

    def test_regenerates_when_two_above(self):
        w = self._worker()
        w._ollama_call = MagicMock(side_effect=["c1 hard", "b1 easy"])
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   side_effect=[{"band": "C1", "n_words": 500},
                                {"band": "B1", "n_words": 500}]):
            out = w._generate_validated_chunk(
                "m", lambda note: f"PROMPT[{note}]", "B1", "lbl", 0.4
            )
        assert out == "b1 easy"
        assert w._ollama_call.call_count == 2
        # second call's prompt carried a non-empty simplify note
        assert "PROMPT[]" not in w._ollama_call.call_args_list[1].args[1]

    def test_caps_retries_and_keeps_last(self):
        w = self._worker()
        w._ollama_call = MagicMock(side_effect=["a", "b", "c"])
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "C2", "n_words": 500}):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4, max_retries=2
            )
        assert out == "c"                       # last attempt kept
        assert w._ollama_call.call_count == 3   # 1 + 2 retries

    def test_skips_gate_when_profiler_absent(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="whatever")
        with patch("level_detector.PROFILER_AVAILABLE", False):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4
            )
        assert out == "whatever"
        w._ollama_call.assert_called_once()

    def test_skips_gate_for_short_chunk(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="tiny")
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "C2", "n_words": 40}):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4, min_words=150
            )
        assert out == "tiny"
        w._ollama_call.assert_called_once()     # no regeneration on a tiny chunk

    def test_returns_none_on_call_failure(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value=None)
        out = w._generate_validated_chunk(
            "m", lambda note: "P", "B1", "lbl", 0.4
        )
        assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::TestValidatedChunk -v`
Expected: FAIL with `AttributeError: 'ProcessingWorker' object has no attribute '_generate_validated_chunk'`

- [ ] **Step 3: Write the helper**

Add `_generate_validated_chunk` to `ProcessingWorker` (place it next to
`_run_level_check`). Lazy-import `level_detector` and `prompts.build_simplify_note`
inside the method. Access the gate and helpers as module attributes
(`level_detector.PROFILER_AVAILABLE`, `level_detector.profile_text`,
`level_detector.band_distance`) — not via `from level_detector import ...` —
so the tests' `patch("level_detector....")` calls take effect. Follow the
behaviour spec above. The first `_ollama_call`
returning `None` returns `None` immediately. Profiler-absent / short-chunk paths
return attempt 0 untouched. Use `level_detector.band_distance(band, target) >= 2`
as the regenerate condition. Log a `"muted"`/`"warning"` line per regeneration so
the user sees why a step is slow.

- [ ] **Step 4: Call it from the chunk loop (only when `level_check == "validate"`)**

Read `validate = cfg.get("level_check") == "validate"` once near the top of
`run()` (alongside the other `cfg` reads). At each of the **three**
Spanish-producing sites, route through the helper when `validate` is set,
otherwise keep the current direct `_ollama_call`:

- **translate:** `build_fn = lambda note: build_translation_prompt(chunk, level, idx, creativity, simplify_note=note)`
- **summarise_key_ideas (es) rewrite:** `build_fn = lambda note: build_rewrite_prompt(summary, level, idx, creativity, simplify_note=note)`
- **summarise_rewrite:** same `build_rewrite_prompt` closure as the key-ideas-es site.

Pattern at each site:

```python
                    if validate:
                        spanish = self._generate_validated_chunk(
                            model, build_fn, level, f"Translate {chunk_label}",
                            temperature,
                        )
                    else:
                        spanish = self._ollama_call(
                            model, build_translation_prompt(chunk, level, idx, creativity),
                            label=f"Translate {chunk_label}", temperature=temperature,
                        )
                    if spanish is None:
                        ...existing fail path unchanged...
```

The English summarise paths (`summarise_only`, key-ideas-en) are **not** wrapped —
validation is Spanish-only. `total_steps`/progress are untouched: regeneration
happens inside an existing step.

- [ ] **Step 5: Run tests + class-boundary guard**

Run: `pytest tests/test_worker.py -v` → Expected: PASS (incl. `TestLevelCheck`).
Run: `grep -n "^class " *.py` → Expected: all classes from CLAUDE.md present,
including `worker.py: class ProcessingWorker(QThread)` (the three-site edit touches
the class body — confirm the declaration survived per CLAUDE.md "Known historical
issues").

- [ ] **Step 6: Update CLAUDE.md + commit**

Extend the "Language-level detector" section (Task 6) and the Pipeline docs: the
`level_check` config key (`off`/`report`/`validate`), that `"validate"`
regenerates Spanish chunks 2+ bands over target (profiler-gated, ≤2 retries,
within-step, Spanish-only, degrades silently when the profiler is absent or the
chunk is under the word floor). Then:

```bash
git add app.py worker.py prompts.py CLAUDE.md tests/test_worker.py
git commit -m "feat: per-chunk language-level validation with regeneration"
```

---

## Self-Review

- **Spec coverage:** CLI (Tasks 1–5), local Ollama LLM-judge (Task 4), spaCy profiler (Task 3), drift/position-awareness (Task 5), gated deps + uv install (Tasks 1, 6). In-app radio + end-of-book report (Task 7). Per-chunk validate+regenerate: pure gate (Task 8), simplify-harder prompt param (Task 9), worker wiring at all three Spanish sites (Task 10). All covered.
- **Placeholder scan:** Frequency source pinned to `wordfreq` (MIT); spaCy model pinned to a wheel URL; band thresholds given concrete starting numbers with a "tunable" note. Regenerate threshold (`>= 2`), retry cap (2), and word floor (150) are concrete. No TODOs.
- **Type consistency:** `assess_document` keys (`whole`/`first_third`/`last_third`/`judge`) match `format_report`'s reads and the Task 7 test's patches. `judge_level` returns `{"verdict","raw"}` consumed consistently. `profile_text` keys (`band`, `n_words`) match `band_from_metrics` inputs and Task 10's reads. `band_distance` consumes `BAND_ORDER` bands, which are exactly what `band_from_metrics`/`profile_text` emit. `_generate_validated_chunk` returns `str | None`, matching the existing `if ... is None:` fail path at every call site.
- **Config consistency:** `level_check` is a single string (`off`/`report`/`validate`) written once in `_build_config`, read in `run()` for both the post-loop report (`in ("report","validate")`) and the per-chunk gate (`== "validate"`), and rides `_on_resume` automatically via `**config` spread. The old boolean `check_level` is fully replaced — no stale references.
- **Degradation paths:** `"validate"` with profiler absent, English output, or a sub-floor chunk all fall back to plain generation with a log line; none fail the run. UI greys the Validate radio when spaCy is absent, so the absent-profiler worker path is reachable only via a resumed/edited config, where it still degrades safely.
