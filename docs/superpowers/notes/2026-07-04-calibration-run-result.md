# Calibration run result — readability does NOT track Spanish CEFR

**Date:** 2026-07-04
**Status:** Calibration attempted; **cefr_cuts.json NOT shipped** (see conclusion)

## What was run

- Deps installed (uv): `textstat`, `datasets`.
- Loaded UniversalCEFR Spanish subsets: `caes_es` (learner essays, 31k), `hablacultura_es` (reference, 713), `kwiqiz_es` (reference, 206). Label field `cefr_level`, text field `text`. **C2 absent from all three** (confirms the spike).
- Scored every text ≥150 words with `textstat.set_lang("es"); textstat.fernandez_huerta(text)`.
- Fit cut points with `calibrate_advisory.fit_cuts` and computed in-sample confusion matrices (in-sample = an upper bound on real accuracy; held-out is worse).

## Per-band median ease (higher = easier)

| Source | A1 | A2 | B1 | B2 | C1 |
|---|---|---|---|---|---|
| learner (caes) | 81.8 | 83.1 | 82.7 | **67.5** | **71.6** |
| reference (hablacultura+kwiziq) | 85.7 | 79.7 | 76.2 | 73.8 | **77.7** |

The relation is **non-monotonic**. Learner: A1–B1 are flat (~82), then B2 (67.5) and C1 (71.6) are **inverted** (C1 reads *easier* than B2). Reference: a faint monotone decline A1→B2 (85.7→73.8), then C1 jumps back up to 77.7 — and N is tiny (B1=66, B2=70, C1=53).

## The decisive finding: the relation is inverted at B2/C1

**B2 median ease (67.5) sits *below* C1's (71.6)** in the learner data — B2 reads
"harder" than C1 by this metric. No threshold scheme can separate an inverted
relationship, so the fit maps B2→C1. This is the unfixable result; it is
stronger evidence than any aggregate accuracy number.

## Per-band recall (in-sample = the ceiling), BookWeaver's B1/B2/C1 range

Restricting to the range BookWeaver targets (the classifier structurally never
emits A1/A2 — `_BAND_ORDER` is C2/C1/B2/B1 with `above='B1'`, so counting A1/A2
unfairly deflates the aggregate):

| true band | recall | where the misses go |
|---|---|---|
| B1 | **82%** (3356/4068) | fine |
| B2 | **19%** (833/4306) | mostly → C1 (inverted) |
| C1 | **39%** (1126/2884) | split B1/B2/C1 |

Aggregate on B1/B2/C1: **5315/11258 = 47%**, vs a **38% majority-class baseline**
(always-guess-B2). So: barely above majority-class, and **failing specifically
at the B2/C1 boundary** — exactly where the advisory would need to work (catching
output too hard for a B1/B2 target). Reference-only collapses C1 to a degenerate
0.8-ease-point band (C1 recall ~2%).

## Conclusion

The honest claim is **not** "readability is uncorrelated with CEFR." In the
*reference* data — the right construct (reading difficulty, not learner
proficiency) — ease is monotone in the correct direction across A1→B2
(85.7→79.7→76.2→73.8). It only breaks at C1, where N is tiny (53). The learner
C1 inversion is likely a construct artifact (an essay measures its writer, not
the text's readability).

So the accurate finding: **a single-feature readability classifier is too weak
and too data-starved (no C2, thin/inverted C1) to calibrate a trustworthy CEFR
band here.** Shipped as "calibrated, primary" it would be a ~47% classifier that
fails at the one boundary that matters — false precision, the exact anti-pattern
this work set out to avoid.

**Decision: do NOT commit `cefr_cuts.json`.** With no cuts file, the shipped code already degrades correctly:
- the end-of-book advisory logs the **raw** Fernández-Huerta number (honest drift signal, makes no CEFR claim);
- `document_band`/report fall back to the spaCy profiler;
- the opt-in validate gate falls back to the profiler band.

The calibration infrastructure (`calibrate_advisory.py`, `readability_band`, `load_cuts`, `document_band`) stays in place so a **better feature set or corpus** can be calibrated later without rework.

## Why this happened / what would actually work

Readability formulas measure surface length/syllable features and are blind to grammar and vocabulary range — the things CEFR actually grades (this was anticipated). To beat ~33% you need either a multi-feature model (readability + subjunctive + rare-word, fit on labeled data) or a proper transformer CEFR classifier (research ceiling ~70% for Spanish, and still no C2 data). Both are larger efforts than an advisory warrants.

## Follow-up: does a 2-feature fit help? (subjunctive tested)

Extracted `subjunctive_ratio`, `mean_sentence_len`, `rare_word_pct` (via
`level_detector.profile_text`) alongside ease on a balanced 600/band B1/B2/C1
sample and fit multinomial logistic models (stratified 70/30 held-out; 33%
majority baseline):

| model | held-out acc | recall B1/B2/C1 |
|---|---|---|
| ease only | 53% | 74/42/43 |
| **ease + subjunctive** | **54%** | 74/41/47 |
| sent_len only | 52% | 74/37/44 |
| ease + sent_len | **61%** | 77/52/53 |
| all four | 60% | 74/53/52 |

Per-band medians (same sample): **subjunctive% is flat — B1 3.45, B2 3.64, C1
3.39** — so it adds essentially nothing (+0.8pt). The one feature that tracks
CEFR monotonically is **mean_sentence_len (13.2 → 18.3 → 21.0)**. Best cheap
model is **ease + sentence-length ≈ 61%**.

**But that 61% is not shippable as a trustworthy advisory:** (a) B2/C1 recall is
still ~52% — a coin flip at the exact boundary that matters; (b) it's fit on
*learner-proficiency* data (wrong construct — measures the writer, not reading
difficulty), and the reference/reading data (right construct) is too small
(~189 rows) to fit a 3-class model; (c) still no C2; (d) it is a logistic model,
not the threshold scheme the shipped `readability_band`/`calibrate_advisory`
use, so shipping it means a persisted model + a runtime spaCy dependency for the
advisory — the same weight as the profiler it was meant to be lighter than.

**Net: subjunctive does not rescue calibration; sentence-length lifts it to
~61% but not to trustworthy, and only on the wrong construct. Recommendation
stands — keep the raw advisory, ship no cuts.**

## Follow-up 2: benchmarking the pre-trained UniversalCEFR classifier

UniversalCEFR publishes two ready-made multilingual A1–C2 classifiers
(`xlm-roberta-base-cefr-all-classifier`, `ModernBERT-base-cefr-all-classifier`)
— the spike missed these. Benchmarked the XLM-R one on Spanish. **Critical
caveat: the "-all" model was fine-tuned on the full UniversalCEFR corpus, which
INCLUDES caes/hablacultura/kwiziq — so every number below is in-sample
(training data), an optimistic upper bound; real generalization is worse.**

| Spanish set | in-sample acc | key per-band |
|---|---|---|
| caes (learner essays) | **99.5%** | pure memorization of training data |
| reference (reading material) | **52.0%** | B2 87%, but **C1 recall 23%** (33/53 C1 → B2) |

Findings:
- The **99.5% on caes is contamination** (memorized homogeneous learner essays)
  — and it's the wrong construct (writer proficiency). The model card's headline
  **F1 0.95** is the same artifact: a random split dominated by the large, easy,
  memorized learner sets. The paper's harder ~69.6% weighted F1 is the more
  honest figure.
- On the **right-construct reading data it manages only 52% in-sample**, and it
  **fails at the B2/C1 boundary exactly like the surface features** (C1 collapses
  to B2). Out-of-sample would be worse.
- It **never predicts C2 for any Spanish text** — cross-lingual C2 transfer does
  not materialize. The C2 gap is not closed by the multilingual model.

**Conclusion on "would a neural net help":** No — not for BookWeaver's need. The
ready-made SOTA transformer, even with a memorization advantage, lands ~52% on
the right construct, reproduces the same B2/C1 failure, and yields no C2. The
impressive numbers are memorized learner-production data. Architecture is not
the bottleneck; **right-construct labeled reading data (with C2) is**, and that
does not exist openly. Recommendation is unchanged and now strongly evidenced:
keep the raw advisory, ship no cuts, don't train or adopt a classifier.

If neural-grade holistic judgement is ever wanted, the existing `judge_level()`
LLM judge is the pragmatic option (no training, reads vocab/grammar directly),
accepting its cost/latency and that it is still not ground truth.

## Reproducibility

UniversalCEFR datasets: `UniversalCEFR/caes_es`, `UniversalCEFR/hablacultura_es`, `UniversalCEFR/kwiqiz_es` (all CC-BY-NC-4.0). Score ≥150-word texts with `textstat.fernandez_huerta` (es), feed `[[ease, band], …]` to `calibrate_advisory.fit_cuts`.
