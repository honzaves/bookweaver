"""calibrate_advisory.py — offline CEFR readability calibration.

Fits Fernández-Huerta ease-score thresholds against CEFR-labeled Spanish text
and emits cefr_cuts.json. UniversalCEFR/cefr_sp_en covers A1–C1 (no open C2
data; Instituto Cervantes C1–C2 material is all-rights-reserved); the C2 cut
is an extrapolated heuristic — see docs/superpowers/notes/2026-07-03-cervantes-corpus-spike.md.
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
