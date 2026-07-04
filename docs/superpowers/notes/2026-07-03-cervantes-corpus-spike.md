# Spike: Cervantes C1–C2 Corpus Availability

**Date:** 2026-07-03  
**Author:** AI spike (Task 6)  
**Status:** DONE — fallback selected

> **Corrections (2026-07-04, after benchmarking — see
> `2026-07-04-calibration-run-result.md`):**
> 1. `UniversalCEFR/cefr_sp_en` is **English** (its `lang` field is 100% `en`),
>    NOT the "primary Spanish dataset." The Spanish data is
>    `caes_es` + `hablacultura_es` + `kwiqiz_es` only; C2 is still absent.
> 2. This spike missed that UniversalCEFR **publishes pre-trained classifiers**
>    (`xlm-roberta-base-cefr-all-classifier`,
>    `ModernBERT-base-cefr-all-classifier`, multilingual A1–C2). They were
>    benchmarked on 2026-07-04: ~52% in-sample on the right-construct Spanish
>    reading data, same B2/C1 collapse, and no C2 predictions for Spanish — so
>    they do not change the fallback decision.

---

## 1. UniversalCEFR — Spanish Subset

**HuggingFace org:** `UniversalCEFR`  
**Primary dataset ID:** `UniversalCEFR/cefr_sp_en`  
**License:** CC-BY-NC-SA-4.0

The Spanish subset is composed of three underlying corpora:

| Corpus (HF name) | Type | Instances | Levels |
|---|---|---|---|
| `caes` | Learner texts (essays) | 30,935 | A1–C1 |
| `hablacultura` | Reference paragraphs | 710 | A2–C1 |
| `kwiziq-es` | Reference documents | 206 | A1–C1 |

**Total: ~31,851 instances. C2 is absent from every Spanish subcorpus.**

The per-level distribution reported in the UniversalCEFR paper (Table 3, arxiv 2506.01419v2):

| A1 | A2 | B1 | B2 | C1 | C2 |
|---|---|---|---|---|---|
| 8,282 | 8,648 | 6,835 | 5,061 | 3,224 | **0** |

**Correction to the task brief:** The brief states UniversalCEFR is "A1–B2 only." This is incorrect. The dataset extends to C1 (3,224 Spanish instances). C2 is missing, not B2.

The CC-BY-NC-SA-4.0 license permits non-commercial research and redistribution with attribution and share-alike terms. This is compatible with BookWeaver's calibration use (non-commercial, internal tooling). The combined Spanish dataset is straightforwardly downloadable via the HuggingFace datasets library.

---

## 2. Instituto Cervantes C1–C2 Material

Three candidate sources were investigated. None is readily obtainable as an openly-licensed research corpus.

### 2a. Plan Curricular del Instituto Cervantes

The Plan Curricular is a three-volume pedagogical framework published by Instituto Cervantes / Biblioteca Nueva (2006). Volume 3 covers C1–C2. A digital edition is freely browsable through the Centro Virtual Cervantes (cvc.cervantes.es).

**What it is:** Linguistic inventories — grammar syllabi, vocabulary lists, functional notions classified by level. It is a *specification* of what C1/C2 learners should master, not a corpus of C1/C2 sample texts.

**Licensing:** "© Instituto Cervantes (España), 1991–2026. Reservados todos los derechos." (all rights reserved). No Creative Commons or research exception is stated anywhere on the site. The legal notice page (cvc.cervantes.es/sobre_cvc/aviso_legal.htm) returned no accessible terms at fetch time.

**Verdict:** Not a text corpus; not licensable without direct negotiation with Instituto Cervantes.

### 2b. DELE C1/C2 Exam Materials

Sample DELE C1 and C2 exam papers are available as PDFs on the examenes.cervantes.es portal. These contain reading comprehension texts at the relevant CEFR level.

**Licensing:** No open license is stated. The papers are published for test-preparation use. Bulk extraction and redistribution for model calibration would require explicit permission from Instituto Cervantes / Universidad de Salamanca (which co-administers the exams). No evidence of a standing research license was found.

**Verdict:** Inaccessible at scale without individual licensing negotiation; not suitable as an automated pipeline input.

### 2c. Other Instituto Cervantes–Adjacent Sources

No other Instituto Cervantes-published C1/C2 text corpus with an open license was found via web search. The broader NLP literature (UniversalCEFR survey, arxiv 2506.01419) does not list any Instituto Cervantes corpus among its 26 source datasets, confirming this is not an established open-research resource.

---

## 3. Fallback Decision

**Situation:**  
- UniversalCEFR provides usable A1–C1 Spanish data (~31k instances; C1 sparse at 3,224).  
- C2 Spanish data: zero instances in any known open corpus.  
- Instituto Cervantes C1/C2 material: not obtainable under an open license without direct negotiation.

**Options considered:**

**(a) LLM-judge labels on a C1/C2 sample**  
Gather a sample of Spanish texts believed to be C1/C2 (e.g., journalistic prose, academic writing, literary texts), run them through an Ollama LLM judge, and use the resulting pseudo-labels to calibrate the C2 cut point.

**(b) Extrapolated heuristic for C1/C2 with documented caveat**  
Fit the Fernández-Huerta → CEFR mapping on A1–C1 data from UniversalCEFR. Extrapolate the C2 threshold by projecting the per-band score distribution below C1 (C2 texts are harder, so they score lower on the readability scale). Document that the C2 threshold is a heuristic extrapolation, not empirically fitted to labeled data.

**Recommendation: Option (b) — extrapolated heuristic with caveat.**

Reasons:

1. **Use-case scope.** BookWeaver's level advisory is designed for simplified Spanish output targeting B1–C1. Texts reaching C2 readability would represent over-generation by the LLM against the user's own CEFR target setting — already flagged by the validate mode's per-chunk regeneration. A C2 cutpoint needs to exist in the schema but is unlikely to be hit in practice.

2. **Extrapolation is defensible.** The Fernández-Huerta scale is monotone: harder texts score lower. Fitting thresholds on the five levels A1–C1 gives a calibration curve that can be extended one band below C1 with reasonable confidence. The uncertainty is bounded (C2 texts differ from C1 texts, but not radically so on surface readability metrics).

3. **LLM-judge labels add fragility.** Option (a) requires selecting a C1/C2 sample corpus (itself an open problem), running Ollama at calibration time, and trusting the judge's accuracy at the adjacent-level boundary (literature reports ~75–80% adjacent-level agreement for LLM-based CEFR judges). This creates a calibration dependency on a specific model and prompt that will drift over time.

4. **Transparency beats false precision.** Documenting the C2 threshold as "extrapolated heuristic" is more honest than presenting LLM-judge pseudolabels as ground truth. A caveat in the calibration module's docstring is sufficient for an advisory tool.

**The caveat to include in the calibration code:**

```
# C2 threshold is an extrapolated heuristic: no open Spanish C2 labeled corpus
# exists (UniversalCEFR/cefr_sp_en has 0 C2 instances; Instituto Cervantes
# material is all-rights-reserved). The value below is derived by extending the
# A1–C1 regression one band below the C1 lower bound. Treat C2 detection as
# approximate: BookWeaver output is unlikely to reach C2 in practice.
```

---

## Sources

- [UniversalCEFR HuggingFace org](https://huggingface.co/UniversalCEFR)
- [UniversalCEFR/cefr_sp_en dataset](https://huggingface.co/datasets/UniversalCEFR/cefr_sp_en)
- [UniversalCEFR/hablacultura_es dataset](https://huggingface.co/datasets/UniversalCEFR/hablacultura_es)
- [UniversalCEFR paper (arxiv 2506.01419v2)](https://arxiv.org/html/2506.01419v2) — Spanish level distribution in Table 3
- [UniversalCEFR project site](https://universalcefr.github.io/)
- [Plan Curricular del Instituto Cervantes — CVC index](https://cvc.cervantes.es/ensenanza/biblioteca_ele/plan_curricular/indice.htm)
- [Instituto Cervantes — Plan Curricular publication page](https://cervantes.org/es/sobre-nosotros/publicaciones/plan-curricular-instituto-cervantes-niveles-referencia-espanol)
- [DELE C1 exam page](https://examenes.cervantes.es/es/dele/examenes/c1)
- [DELE C2 exam page](https://examenes.cervantes.es/es/dele/examenes/c2)
- [Classifying German Language Proficiency with LLMs (arxiv 2512.06483)](https://arxiv.org/pdf/2512.06483) — LLM-judge accuracy context
