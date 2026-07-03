# Language-level control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Spanish language-level control from unreliable post-hoc regeneration to reliable generation-time prompt guidance, and demote all measurement to a calibrated, log-only advisory.

**Architecture:** Four independent phases. Phase 1 tightens per-level prompt guidance and adds before/after example pairs (no new deps). Phase 2 defaults the regenerate gate off and adds a raw `textstat` readability log line. Phase 3 is an offline calibration script producing `cefr_cuts.json`. Phase 4 wires calibrated bands into the detector, the report, and the opt-in gate.

**Tech Stack:** Python 3, PyQt6 (stubbed in tests), Ollama HTTP, spaCy + wordfreq (optional, gated), **textstat (NEW optional dep, gated)**, pytest.

## Global Constraints

- Max line length **100**; `E221` (aligned assignments) suppressed. Run `pycodestyle --statistics *.py`.
- `prompts.py` has **no Qt dependency** and imports nothing project-local.
- `level_detector.py` is Qt-free; **all optional deps sit behind an import gate**. `textstat` MUST be gated exactly like `PROFILER_AVAILABLE` (module-level `TEXTSTAT_AVAILABLE` flag + lazy `import textstat` inside functions). Never import Qt/app/worker/widgets.
- Advisory failures **never fail a run** — degrade to a skipped/omitted log line.
- Tests: `pytest`. `conftest.py` stubs PyQt6 and optional TTS deps; it does **not** stub `textstat` or `spacy`, so gated code must degrade when they are absent.
- Install optional deps with **uv only**: `uv pip install textstat`. Never plain `pip`, never `uv sync`.
- `_ollama_call` has **no default temperature** — always pass it explicitly.
- After any edit touching a class boundary, run `grep -n "^class " *.py` and confirm the expected list in CLAUDE.md.
- Commit after every task.

---

## File Structure

- `prompts.py` — MODIFY: rewrite `_LEVEL_GUIDANCE`; add `_LEVEL_PAIRS` + `_pairs_block()`; inject into `build_translation_prompt` and `build_rewrite_prompt`.
- `level_detector.py` — MODIFY: add `TEXTSTAT_AVAILABLE` gate + `textstat_readability()`; later `readability_band()`, `load_cuts()`, `document_band()`; retire `CEFR_THRESHOLDS` as primary (keep as fallback + keep `subjunctive_ratio`).
- `app.py` — MODIFY: mark the Validate radio experimental (label/tooltip). (Default is already Off at `app.py:357`.)
- `worker.py` — MODIFY: add `_readability_line()` static helper + call in `_run_level_check`; later switch band source in `_generate_validated_chunk`.
- `calibrate_advisory.py` — CREATE: offline calibration CLI with pure `fit_cuts()` / `confusion_matrix()` helpers.
- `cefr_cuts.json` — CREATE (Phase 3 output): calibrated thresholds consumed by Phase 4.
- Tests: `tests/test_prompts.py`, `tests/test_level_detector.py`, `tests/test_worker.py`, `tests/test_calibrate_advisory.py` (new).

---

## Phase 1 — Generation-time control (prompts.py)

### Task 1: Operational constraints in `_LEVEL_GUIDANCE`

**Files:**
- Modify: `prompts.py:19-42`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `_LEVEL_GUIDANCE` dict unchanged shape (`dict[str,str]`, keys `B1/B2/C1/C2`), richer values.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py
def test_b1_guidance_caps_sentence_length():
    assert "12 words" in prompts._LEVEL_GUIDANCE["B1"]

def test_b2_guidance_caps_sentence_length():
    assert "18 words" in prompts._LEVEL_GUIDANCE["B2"]

def test_b1_guidance_avoids_subjunctive():
    assert "subjunctive" in prompts._LEVEL_GUIDANCE["B1"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompts.py::test_b1_guidance_caps_sentence_length -v`
Expected: FAIL (`"12 words"` not present).

- [ ] **Step 3: Replace the `_LEVEL_GUIDANCE` dict body**

```python
_LEVEL_GUIDANCE: dict[str, str] = {
    "B1": (
        "Keep sentences short — aim for 12 words or fewer. Use only the "
        "present and the simple past (pretérito). Avoid the subjunctive, the "
        "conditional, and compound or literary tenses. No idioms and no "
        "subordinate clauses beyond a simple 'que'. Use only high-frequency, "
        "everyday vocabulary."
    ),
    "B2": (
        "Keep most sentences under 18 words. Use present, past (pretérito and "
        "imperfecto), future and conditional naturally; use the subjunctive "
        "sparingly and only in common constructions. A few common idioms are "
        "fine. Prefer common vocabulary and avoid rare or literary terms."
    ),
    "C1": (
        "Write natural, fluid Spanish prose with full command of tenses "
        "including the subjunctive. Use idiomatic and figurative language "
        "where it fits. Vary sentence length and rhythm for literary effect, "
        "but keep it readable."
    ),
    "C2": (
        "Write at native literary level: full command of all tenses, complex "
        "subjunctive and conditional constructions, rich vocabulary, register "
        "variation, rhythm and literary devices."
    ),
}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_prompts.py -v`
Expected: PASS (existing `_LEVEL_GUIDANCE` presence/distinctness tests still pass).

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: operational per-level constraints in _LEVEL_GUIDANCE"
```

---

### Task 2: Before/after pairs + injection into body-producing prompts

**Files:**
- Modify: `prompts.py` (add `_LEVEL_PAIRS` + `_pairs_block()` after `_LEVEL_GUIDANCE`; edit `build_translation_prompt:170-211` and `build_rewrite_prompt:214-249`)
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `_pairs_block(level: str) -> str` — returns a delimited examples+separator block for `B1`/`B2`, and `""` for any other level (so C1/C2/unknown prompts stay byte-identical to before this task). Injected immediately before the `SOURCE …` line in both builders.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py
def test_b1_translation_includes_example_pairs():
    p = build_translation_prompt("Hello.", level="B1", chapter_index=0)
    assert "LEVEL EXAMPLES" in p
    assert "Instead of" in p and "Write:" in p

def test_c1_translation_has_no_example_block():
    p = build_translation_prompt("Hello.", level="C1", chapter_index=0)
    assert "LEVEL EXAMPLES" not in p

def test_b1_rewrite_includes_bleed_separator():
    p = build_rewrite_prompt("Summary.", level="B1", chapter_index=0)
    assert "USE ONLY THE ACTUAL SOURCE" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompts.py::test_b1_translation_includes_example_pairs -v`
Expected: FAIL (`"LEVEL EXAMPLES"` not present).

- [ ] **Step 3: Add data + renderer after `_LEVEL_GUIDANCE`**

```python
# Before/after simplification pairs. Only B1/B2 need active correction;
# C1/C2 rely on constraints (leaving their prompts byte-stable). Pairs carry
# no narrative, so nothing content-like can bleed into the output.
_LEVEL_PAIRS: dict[str, list[tuple[str, str]]] = {
    "B1": [
        ("A pesar de las inclemencias del tiempo, decidieron proseguir su "
         "travesía.",
         "Aunque hacía mal tiempo, decidieron seguir su viaje."),
        ("Se hallaba sumido en una profunda melancolía cuya causa desconocía.",
         "Estaba muy triste y no sabía por qué."),
    ],
    "B2": [
        ("Se hallaba sumido en una profunda melancolía cuya causa se le "
         "escapaba.",
         "Estaba muy triste, aunque no entendía del todo por qué se sentía "
         "así."),
        ("Perseveró, no obstante las adversidades que se cernían sobre él.",
         "Siguió adelante, a pesar de los problemas que tenía por delante."),
    ],
}


def _pairs_block(level: str) -> str:
    """Render before/after example pairs for *level* as a delimited reference
    block with a hard bleed separator. Empty string for levels without pairs,
    keeping their prompt output byte-identical."""
    pairs = _LEVEL_PAIRS.get(level)
    if not pairs:
        return ""
    lines = "\n".join(
        f"- Instead of: «{hard}»\n  Write: «{easy}»" for hard, easy in pairs
    )
    return (
        "LEVEL EXAMPLES (style/difficulty reference ONLY — do NOT translate, "
        "copy, or reuse their words or content):\n"
        f"{lines}\n\n"
        "USE ONLY THE ACTUAL SOURCE BELOW.\n\n"
    )
```

- [ ] **Step 4: Inject into `build_translation_prompt`**

In `prompts.py:170-211`, change the final source line from:

```python
        f"{context_block}"
        f"SOURCE TEXT (English):\n{chunk_text}\n"
```

to:

```python
        f"{context_block}"
        f"{_pairs_block(level)}"
        f"SOURCE TEXT (English):\n{chunk_text}\n"
```

- [ ] **Step 5: Inject into `build_rewrite_prompt`**

In `prompts.py:214-249`, change the final source line from:

```python
        f"{context_block}"
        f"SOURCE SUMMARY (English):\n{summary}\n"
```

to:

```python
        f"{context_block}"
        f"{_pairs_block(level)}"
        f"SOURCE SUMMARY (English):\n{summary}\n"
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_prompts.py -v`
Expected: PASS. Then `pycodestyle --statistics prompts.py` → no new errors.

- [ ] **Step 7: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: before/after level example pairs with bleed guard"
```

---

## Phase 2 — Default gate off + raw readability tripwire

### Task 3: Mark the Validate radio experimental (app.py)

**Files:**
- Modify: `app.py:354-356`

**Interfaces:** none (UI-only; `app.py` is not unit-tested — Qt is stubbed).

- [ ] **Step 1: Change the radio label + add a tooltip**

Replace `app.py:354-356`:

```python
        self._level_validate_radio = QRadioButton(
            "Validate each chunk (regenerate if 2+ levels too hard) + report"
        )
```

with:

```python
        self._level_validate_radio = QRadioButton(
            "Validate each chunk — experimental, unreliable (regenerate if "
            "2+ levels too hard) + report"
        )
        self._level_validate_radio.setToolTip(
            "Per-chunk CEFR gating is a proxy and often misfires; leave Off "
            "unless experimenting. Off is the default."
        )
```

(The default already selects Off at `app.py:357` — do not change that.)

- [ ] **Step 2: Sanity-check the class boundary**

Run: `grep -n "^class " app.py`
Expected: `class BookWeaverApp(QMainWindow)` present.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "chore: flag per-chunk validate as experimental in the UI"
```

---

### Task 4: `TEXTSTAT_AVAILABLE` gate + `textstat_readability()`

**Files:**
- Modify: `level_detector.py` (add gate near `PROFILER_AVAILABLE:20-28`; add function near the profiler section)
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Produces: `textstat_readability(text: str) -> float | None` — raw Fernández-Huerta ease (higher = easier), rounded to 1 dp; `None` when textstat is unavailable. Module flag `TEXTSTAT_AVAILABLE: bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_level_detector.py
import level_detector

def test_textstat_readability_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(level_detector, "TEXTSTAT_AVAILABLE", False)
    assert level_detector.textstat_readability("Hola mundo.") is None

def test_textstat_readability_returns_float_when_available(monkeypatch):
    monkeypatch.setattr(level_detector, "TEXTSTAT_AVAILABLE", True)
    fake = type("T", (), {"set_lang": staticmethod(lambda l: None),
                          "fernandez_huerta": staticmethod(lambda t: 72.34)})
    monkeypatch.setitem(__import__("sys").modules, "textstat", fake)
    assert level_detector.textstat_readability("Hola mundo.") == 72.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::test_textstat_readability_none_when_unavailable -v`
Expected: FAIL (`AttributeError: TEXTSTAT_AVAILABLE` / function missing).

- [ ] **Step 3: Add the gate + function**

Add after the `PROFILER_AVAILABLE` gate block (`level_detector.py:28`):

```python
TEXTSTAT_AVAILABLE = False
try:
    import textstat  # noqa: F401
    TEXTSTAT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatch
    pass
```

Add near the feature-profiler section:

```python
def textstat_readability(text: str) -> float | None:
    """Raw Fernández-Huerta readability ease for Spanish *text* (higher =
    easier). Returns None when textstat is unavailable. Uncalibrated — for
    advisory logging and drift-spotting only, never a gate."""
    if not TEXTSTAT_AVAILABLE:
        return None
    import textstat
    textstat.set_lang("es")
    return round(textstat.fernandez_huerta(text), 1)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_level_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: gated raw textstat readability helper"
```

---

### Task 5: Log the raw readability in `_run_level_check`

**Files:**
- Modify: `worker.py` (add static helper near `_run_level_check:514`; call inside it after the report loop `worker.py:534-537`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `level_detector.textstat_readability` (Task 4).
- Produces: `ProcessingWorker._readability_line(body: str) -> str | None` — a formatted log line, or `None` when textstat is unavailable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py
import level_detector
from worker import ProcessingWorker

def test_readability_line_formats_score(monkeypatch):
    monkeypatch.setattr(level_detector, "textstat_readability", lambda b: 64.0)
    line = ProcessingWorker._readability_line("Texto en español.")
    assert "64.0" in line and "Fernández" in line

def test_readability_line_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(level_detector, "textstat_readability", lambda b: None)
    assert ProcessingWorker._readability_line("Texto.") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::test_readability_line_formats_score -v`
Expected: FAIL (`AttributeError: _readability_line`).

- [ ] **Step 3: Add the static helper**

Add inside `class ProcessingWorker`, next to `_run_level_check`:

```python
    @staticmethod
    def _readability_line(body: str) -> str | None:
        """Format the raw (uncalibrated) readability advisory line, or None
        when textstat is unavailable. Log-only; never triggers regeneration."""
        import level_detector
        score = level_detector.textstat_readability(body)
        if score is None:
            return None
        return f"Readability (Fernández Huerta, raw ease): {score}"
```

- [ ] **Step 4: Call it in `_run_level_check`**

In `worker.py`, immediately after the `format_report(...).splitlines()` emit loop (`worker.py:534-537`), before the `except`, add:

```python
            line = self._readability_line(body)
            if line:
                self.log.emit(f"   {line}", "muted")
```

- [ ] **Step 5: Run tests + class-boundary check**

Run: `pytest tests/test_worker.py -v`
Expected: PASS.
Run: `grep -n "^class " worker.py`
Expected: `class ProcessingWorker(QThread)` present.

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: log raw readability advisory in end-of-book level check"
```

---

## Phase 3 — Calibration pipeline (offline, spike-gated)

### Task 6: Spike — Cervantes C1–C2 corpus availability

**Files:**
- Create: `docs/superpowers/notes/2026-07-03-cervantes-corpus-spike.md`

**Not a code task — no test.** Deliverable is a written findings note and a go/no-go decision. Acceptance:

- [ ] **Step 1: Investigate** whether Instituto Cervantes graded C1–C2 Spanish material is obtainable/licensable for use as calibration labels (Plan Curricular corpora, DELE preparation texts, licensing terms). Record sources + licensing.
- [ ] **Step 2: Decide fallback** if unavailable: (a) LLM-judge labels on a C1/C2 sample, or (b) leave C1/C2 cut points as raw-ease heuristics with a documented caveat. Write the chosen fallback into the note.
- [ ] **Step 3: Commit** the note.

```bash
git add docs/superpowers/notes/2026-07-03-cervantes-corpus-spike.md
git commit -m "docs: Cervantes C1-C2 corpus spike findings + fallback decision"
```

> **Gate:** Tasks 7–10 proceed regardless (they degrade gracefully), but the *quality* of C1/C2 cut points depends on this outcome.

---

### Task 7: `calibrate_advisory.py` with pure `fit_cuts` / `confusion_matrix`

**Files:**
- Create: `calibrate_advisory.py`
- Test: `tests/test_calibrate_advisory.py`

**Interfaces:**
- Produces:
  - `fit_cuts(scored: list[tuple[float, str]]) -> dict` — input `(ease_score, band)` rows; output `{"formula": "fernandez_huerta", "thresholds": [[thr, band], …], "above": band}` where `thresholds` is ascending by `thr`, each `band` is the label for scores **below** that threshold (hardest first), and `above` is the easiest band. Thresholds are the midpoints between adjacent bands' median ease.
  - `confusion_matrix(scored, cuts) -> dict[tuple[str, str], int]` — keyed `(true_band, predicted_band)`.
  - Consumed by Task 8's `readability_band`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calibrate_advisory.py
from calibrate_advisory import fit_cuts, confusion_matrix

SCORED = (  # easier band => higher ease score
    [(90.0, "B1")] * 5 + [(70.0, "B2")] * 5 +
    [(50.0, "C1")] * 5 + [(30.0, "C2")] * 5
)

def test_thresholds_are_ascending_and_monotonic():
    cuts = fit_cuts(SCORED)
    thrs = [t for t, _ in cuts["thresholds"]]
    assert thrs == sorted(thrs)

def test_bands_ordered_hardest_first():
    cuts = fit_cuts(SCORED)
    bands = [b for _, b in cuts["thresholds"]] + [cuts["above"]]
    assert bands == ["C2", "C1", "B2", "B1"]

def test_confusion_matrix_perfect_on_separable_data():
    cuts = fit_cuts(SCORED)
    cm = confusion_matrix(SCORED, cuts)
    off_diagonal = sum(n for (t, p), n in cm.items() if t != p)
    assert off_diagonal == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calibrate_advisory.py -v`
Expected: FAIL (`ModuleNotFoundError: calibrate_advisory`).

- [ ] **Step 3: Write `calibrate_advisory.py`**

```python
"""calibrate_advisory.py — offline CEFR readability calibration.

Fits Fernández-Huerta ease-score thresholds against CEFR-labeled Spanish text
(UniversalCEFR for A1-B2, Cervantes for C1-C2) and emits cefr_cuts.json.
Run once, offline. Not imported by the app at runtime — only the emitted
cefr_cuts.json is consumed (see level_detector.readability_band)."""
from __future__ import annotations

import json
from statistics import median

# Hardest -> easiest. Restrict to the bands BookWeaver targets.
_BAND_ORDER = ["C2", "C1", "B2", "B1"]


def fit_cuts(scored: list[tuple[float, str]]) -> dict:
    """Fit ascending ease-score thresholds from (ease_score, band) rows.
    Each threshold is the midpoint of adjacent bands' median ease; the label
    attached to a threshold is the band for scores BELOW it (hardest first)."""
    by_band: dict[str, list[float]] = {}
    for score, band in scored:
        by_band.setdefault(band, []).append(score)
    meds = {b: median(v) for b, v in by_band.items() if v}
    present = [b for b in _BAND_ORDER if b in meds]  # hardest -> easiest
    thresholds = []
    for harder, easier in zip(present, present[1:]):
        thr = (meds[harder] + meds[easier]) / 2
        thresholds.append([round(thr, 2), harder])
    thresholds.sort(key=lambda tb: tb[0])
    above = present[-1] if present else "B1"
    return {"formula": "fernandez_huerta", "thresholds": thresholds,
            "above": above}


def band_for_score(score: float, cuts: dict) -> str:
    """Map an ease score to a band using fitted thresholds (shared logic with
    level_detector.readability_band)."""
    for thr, band in cuts["thresholds"]:
        if score < thr:
            return band
    return cuts["above"]


def confusion_matrix(scored: list[tuple[float, str]],
                     cuts: dict) -> dict[tuple[str, str], int]:
    cm: dict[tuple[str, str], int] = {}
    for score, true_band in scored:
        pred = band_for_score(score, cuts)
        cm[(true_band, pred)] = cm.get((true_band, pred), 0) + 1
    return cm


def _print_confusion(cm: dict[tuple[str, str], int]) -> None:
    total = sum(cm.values()) or 1
    correct = sum(n for (t, p), n in cm.items() if t == p)
    print(f"Accuracy: {correct}/{total} = {correct / total:.1%}")
    for (t, p), n in sorted(cm.items()):
        mark = "" if t == p else "  <-- misclassified"
        print(f"  true={t} pred={p}: {n}{mark}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Calibrate CEFR ease cuts.")
    parser.add_argument("--scores", required=True,
                        help="JSON file: [[ease_score, band], ...]")
    parser.add_argument("--out", default="cefr_cuts.json")
    args = parser.parse_args(argv)

    scored = [(float(s), b) for s, b in json.load(open(args.scores))]
    cuts = fit_cuts(scored)
    _print_confusion(confusion_matrix(scored, cuts))
    json.dump(cuts, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"Wrote {args.out}: {cuts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_calibrate_advisory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add calibrate_advisory.py tests/test_calibrate_advisory.py
git commit -m "feat: offline readability calibration script (fit_cuts + confusion)"
```

> **Manual, post-spike:** produce a real `[[ease, band], …]` scores file from the corpora (score each text with `textstat.fernandez_huerta` at ≥150 words), run `python calibrate_advisory.py --scores scores.json`, review the printed confusion matrix, and commit the emitted `cefr_cuts.json`.

---

## Phase 4 — Wire calibrated bands in (level_detector.py + worker.py)

### Task 8: `load_cuts()` + `readability_band()`

**Files:**
- Modify: `level_detector.py`
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Consumes: the `cefr_cuts.json` schema from Task 7 (`{"thresholds": [[thr, band], …], "above": band}`).
- Produces:
  - `load_cuts(path: str = "cefr_cuts.json") -> dict | None` — parsed cuts, or `None` if the file is missing/unreadable.
  - `readability_band(text: str, cuts: dict) -> str | None` — calibrated band, or `None` when textstat is unavailable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_level_detector.py
CUTS = {"formula": "fernandez_huerta",
        "thresholds": [[40.0, "C2"], [60.0, "C1"], [80.0, "B2"]],
        "above": "B1"}

def test_readability_band_maps_scores(monkeypatch):
    monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 50.0)
    assert level_detector.readability_band("x", CUTS) == "C1"
    monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 95.0)
    assert level_detector.readability_band("x", CUTS) == "B1"
    monkeypatch.setattr(level_detector, "textstat_readability", lambda t: 30.0)
    assert level_detector.readability_band("x", CUTS) == "C2"

def test_readability_band_none_without_textstat(monkeypatch):
    monkeypatch.setattr(level_detector, "textstat_readability", lambda t: None)
    assert level_detector.readability_band("x", CUTS) is None

def test_load_cuts_missing_file_returns_none():
    assert level_detector.load_cuts("does_not_exist_xyz.json") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::test_readability_band_maps_scores -v`
Expected: FAIL (`AttributeError: readability_band`).

- [ ] **Step 3: Add both functions**

```python
def load_cuts(path: str = "cefr_cuts.json") -> dict | None:
    """Load calibrated ease-score cut points, or None if absent/unreadable."""
    import json
    import os
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def readability_band(text: str, cuts: dict) -> str | None:
    """Calibrated CEFR band for *text* via fitted ease thresholds. None when
    textstat is unavailable. Thresholds ascending; label = band for scores
    below the threshold (hardest first)."""
    score = textstat_readability(text)
    if score is None:
        return None
    for thr, band in cuts["thresholds"]:
        if score < thr:
            return band
    return cuts["above"]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_level_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: calibrated readability_band + cuts loader"
```

---

### Task 9: `document_band()` — calibrated primary, profiler fallback

**Files:**
- Modify: `level_detector.py` (add `document_band`; use it in `format_report:229-258` band line)
- Test: `tests/test_level_detector.py`

**Interfaces:**
- Consumes: `readability_band` (Task 8), existing `profile_text`/`band_from_metrics`.
- Produces: `document_band(text: str, cuts: dict | None) -> str | None` — calibrated band when `cuts` present and textstat available; else the profiler band (`profile_text(text)["band"]`); else `None`. This makes calibrated textstat the **primary** band and demotes `CEFR_THRESHOLDS`/`band_from_metrics` to a fallback (kept, not deleted, so subjunctive metrics and no-cuts operation still work).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_level_detector.py
def test_document_band_prefers_calibrated(monkeypatch):
    monkeypatch.setattr(level_detector, "readability_band", lambda t, c: "B2")
    assert level_detector.document_band("x", CUTS) == "B2"

def test_document_band_falls_back_to_profiler(monkeypatch):
    monkeypatch.setattr(level_detector, "readability_band", lambda t, c: None)
    monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", True)
    monkeypatch.setattr(level_detector, "profile_text", lambda t: {"band": "C1"})
    assert level_detector.document_band("x", None) == "C1"

def test_document_band_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(level_detector, "readability_band", lambda t, c: None)
    monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", False)
    assert level_detector.document_band("x", None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_level_detector.py::test_document_band_prefers_calibrated -v`
Expected: FAIL (`AttributeError: document_band`).

- [ ] **Step 3: Add `document_band`**

```python
def document_band(text: str, cuts: dict | None) -> str | None:
    """Primary CEFR band for *text*: calibrated readability when cuts are
    present and textstat is available; otherwise the deterministic profiler
    band; otherwise None. Calibrated is primary — CEFR_THRESHOLDS is only the
    fallback path now."""
    if cuts is not None:
        band = readability_band(text, cuts)
        if band is not None:
            return band
    if PROFILER_AVAILABLE:
        return profile_text(text)["band"]
    return None
```

- [ ] **Step 4: Surface it in `format_report`**

No signature change to `format_report` — pass the band through the assessment
dict. In `assess_document` (`level_detector.py:208-226`), before `return out`,
add:

```python
    out["calibrated_band"] = document_band(text, load_cuts())
```

Then in `format_report` (`level_detector.py:229-258`), just after the line
list is initialised (`lines = [...]`), add a calibrated line when present. It
reads from the dict with `.get`, so hand-built assessment dicts in existing
tests (which lack the key) are unaffected:

```python
    cal = assessment.get("calibrated_band")
    if cal:
        lines.append(f"Calibrated band: {cal}  (readability-based, primary)")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_level_detector.py -v`
Expected: PASS (existing `assess_document`/`format_report` tests still pass; the new key is additive).

- [ ] **Step 6: Commit**

```bash
git add level_detector.py tests/test_level_detector.py
git commit -m "feat: calibrated document_band as primary, profiler as fallback"
```

---

### Task 10: Switch the opt-in gate's band source to calibrated

**Files:**
- Modify: `worker.py:559-609` (`_generate_validated_chunk`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `level_detector.document_band` (Task 9), `level_detector.load_cuts` (Task 8), existing `profile_text` (for `n_words` floor + subjunctive) and `band_distance`.
- Produces: no new public interface; the gate now bands via `document_band` (calibrated primary) instead of `profile_text(...)["band"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py — verify the gate consults the calibrated band source
def test_validated_chunk_uses_document_band(monkeypatch):
    import level_detector
    calls = {"n": 0}
    def fake_document_band(text, cuts):
        calls["n"] += 1
        return "B1"  # at/below target => accept, no regeneration
    monkeypatch.setattr(level_detector, "load_cuts", lambda: {"x": 1})
    monkeypatch.setattr(level_detector, "document_band", fake_document_band)
    monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", True)
    monkeypatch.setattr(level_detector, "profile_text",
                        lambda t: {"band": "C1", "n_words": 300})

    w = ProcessingWorker.__new__(ProcessingWorker)
    w._timeout = 1
    w._abort = False
    w.log = type("S", (), {"emit": lambda *a, **k: None})()
    w._ollama_call = lambda *a, **k: "un texto en español " * 60
    out = w._generate_validated_chunk(
        "m", lambda note: "prompt", "B1", "Translate 1.1/1", 0.3)
    assert out is not None
    assert calls["n"] >= 1  # gate consulted the calibrated band
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::test_validated_chunk_uses_document_band -v`
Expected: FAIL (gate still bands via `profile_text(...)["band"]`; `document_band` never called).

- [ ] **Step 3: Edit `_generate_validated_chunk`**

In `worker.py`, at the top of the function body load cuts once (after the
existing `import level_detector`):

```python
        import level_detector
        from prompts import build_simplify_note
        cuts = level_detector.load_cuts()
```

Then inside the retry loop, replace the banding. Current (`worker.py:571-579`):

```python
        for attempt in range(max_retries + 1):
            m = level_detector.profile_text(text)
            if m["n_words"] < min_words:
                ...
            if level_detector.band_distance(m["band"], target_level) < 2:
                return text
```

becomes:

```python
        for attempt in range(max_retries + 1):
            m = level_detector.profile_text(text)
            if m["n_words"] < min_words:
                ...  # unchanged floor-skip block
            band = level_detector.document_band(text, cuts) or m["band"]
            if level_detector.band_distance(band, target_level) < 2:
                return text
```

Also update the two log lines that reference `m['band']` (`worker.py:583`,
`592`) to use `band` so the message matches the gating decision:

```python
                    f"   ⚠️  {label}: still {band} after {max_retries} "
```
```python
                f"   ⚠️  {label}: assessed {band} vs target "
```

And build the simplify note from `band` too (`worker.py:598`):

```python
                model, build_fn(build_simplify_note(band, target_level)),
```

- [ ] **Step 4: Run tests + class-boundary check**

Run: `pytest tests/test_worker.py -v`
Expected: PASS.
Run: `grep -n "^class " worker.py`
Expected: `class ProcessingWorker(QThread)` present.

- [ ] **Step 5: Full suite + style**

Run: `pytest -q`
Expected: only the one pre-existing `test_settings.py::TestOllamaTimeout::test_defaults_when_missing` failure documented in CLAUDE.md; everything else green.
Run: `pycodestyle --statistics worker.py level_detector.py prompts.py`
Expected: no new violations.

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: opt-in validate gate bands via calibrated readability"
```

---

## Post-implementation

- Update `CLAUDE.md` "Language-level detector" section: textstat gate, calibrated `document_band` as primary, `CEFR_THRESHOLDS` demoted to fallback, `validate` default-off + experimental, and the raw readability advisory line.
- Add `textstat` to the optional-deps install note (uv only).
