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
