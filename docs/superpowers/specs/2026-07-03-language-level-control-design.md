# Language-level control — design spec

**Date:** 2026-07-03
**Status:** Approved for planning

## Problem

BookWeaver's `validate` mode regenerates any Spanish chunk assessed 2+ CEFR
bands above the target, using a deterministic spaCy profiler
(`level_detector.profile_text` + hand-typed `CEFR_THRESHOLDS`). In practice the
profiler mismeasures natural Spanish prose — the surface-form rare-word metric
runs hot and the B1 subjunctive cap (≤1%) is unreachable for narrative — so
targeting B1 causes near-constant regeneration that never converges. The
underlying truth: automated per-chunk CEFR scoring is unreliable for Spanish
(research ceiling ~70% weighted F1, and no drop-in calibrated library exists).

## Goal

Move language-level control from *post-hoc measurement* (unreliable) to
*generation-time guidance* (reliable), and demote all measurement to an
**advisory** signal that never silently drives expensive regeneration. Where a
deterministic score is still used, make it **calibrated against labeled data**
rather than hand-typed.

## Non-goals

- Building a research-grade CEFR classifier. The advisory is explicitly a
  readability proxy with a known, printed error rate.
- Making per-chunk gating the default. Gating stays opt-in and off by default.

## Approach (value-first, four phases)

Phase 1 ships the reliable lever immediately with no external dependencies.
Phases 3–4 (calibration) are a clean follow-on that upgrades the advisory from a
raw number to a calibrated band without reworking earlier phases.

### Phase 1 — Generation-time control (`prompts.py`)

- Rewrite `_LEVEL_GUIDANCE[level]` for B1/B2/C1/C2 to carry **operational
  constraints** — max sentence length, tense limits, subjunctive guidance,
  vocabulary-frequency direction — instead of abstract prose.
- Add a per-level set of **2–3 before/after simplification pairs**
  (`complejo → simple`), rendered into `build_translation_prompt` and
  `build_rewrite_prompt` in their own delimited block labelled as a
  style/level reference that must not be reused as content.
- **Bleed guard:** pairs carry no narrative; a hard
  `TRANSLATE ONLY THE TEXT BELOW` separator sits between the reference block
  and the source text.
- No dependency on corpus or textstat. Pure prompt work.

### Phase 2 — Turn off the gate + raw tripwire

- UI: the `validate` radio **defaults to off**, with a label noting it is
  experimental/unreliable. `_generate_validated_chunk` stays in the code as an
  opt-in path.
- Add a **log-only** readability readout: `textstat.fernandez_huerta` (raw,
  uncalibrated) per chapter, printed alongside the existing level report. It
  never triggers regeneration. Guarded by `find_spec("textstat")` so absence
  degrades to a skipped log line.

### Phase 3 — Calibration pipeline (offline)

- **Spike first:** can Instituto Cervantes C1–C2 material be obtained/licensed
  for labels? If not, fall back to (a) LLM-judge labels on a sample, or (b)
  leaving C1/C2 cut points as raw-ease heuristics with a documented caveat.
- `calibrate_advisory.py` (offline, one-shot): load UniversalCEFR (A1–C1; no open C2 data) +
  Cervantes (C1–C2, not openly licensed — see spike note), score with `fernandez_huerta`,
  fit cut points (median-crossover or ordinal logistic), **print a held-out confusion
  matrix**, and emit `cefr_cuts.json`. The C2 cut is an extrapolated heuristic.

### Phase 4 — Wire calibrated bands in (`level_detector.py`)

- New `readability_band(text, cuts)` loads `cefr_cuts.json`; **calibrated
  textstat becomes the primary deterministic band.** Retire the hand-typed
  `CEFR_THRESHOLDS`.
- Keep spaCy only to supply `subjunctive_ratio`; an optional 2-feature model
  (`ease + subjunctive`) is added **only if** the Phase 3 confusion matrix
  shows the single feature is too weak.
- Both the Phase 2 tripwire and the opt-in `validate` gate consume the
  calibrated band; the gate's regenerate threshold stays `band_distance >= 2`.

## Data flow

```
source EN
  → build_*_prompt (operational constraints + before/after pairs)
  → Ollama
  → Spanish chunk
  → [advisory] readability_band(chunk, cuts)
  → log line
  → regenerate ONLY IF validate opt-in is ON
```

## Error handling

- textstat / corpus / spaCy absent → advisory degrades to a skipped log line;
  **never fails a run** (matches the existing profiler-gate behavior).
- Cervantes spike fails → documented fallback; C1/C2 flagged lower-confidence;
  does not block Phases 1–2.

## Testing

- **Phase 1:** unit-test that constraints/pairs render for each level; assert
  the default (empty simplify note) prompt output stays byte-stable where
  expected; manual grep-for-bleed check on 2–3 real chapters.
- **Phase 2:** unit-test the tripwire is log-only (no regeneration path
  reached) and is guarded when textstat is absent.
- **Phase 3:** `calibrate_advisory.py` prints a confusion matrix; emitted cut
  points are monotonic across bands.
- **Phase 4:** `readability_band` maps known scores to expected bands and
  degrades gracefully when `cefr_cuts.json` is missing.

## Open questions

1. **Cervantes C1–C2 corpus** — availability and licensing (Phase 3 spike).
2. **Single- vs 2-feature calibration** — decided by the Phase 3 confusion
   matrix, not up front.

## Sequencing / dependencies

- Phase 1 — standalone; ships value immediately.
- Phase 2 — depends only on textstat being importable (raw tripwire).
- Phase 3 — gated by the Cervantes spike; produces `cefr_cuts.json`.
- Phase 4 — depends on Phase 3 output; upgrades tripwire + opt-in gate to
  calibrated bands.
