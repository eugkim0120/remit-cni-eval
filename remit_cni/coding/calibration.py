"""Calibration statistics against Eugene's hand codes (50 pilot runs)."""
KAPPA_MIN = 0.6
BREACH_RECALL_MIN = 0.9


def cohen_kappa(a: list, b: list) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("label lists must be non-empty and equal length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(k) / n) * (b.count(k) / n) for k in set(a) | set(b))
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def recall(pred: list[bool], gold: list[bool]) -> float:
    positives = [p for p, g in zip(pred, gold) if g]
    if not positives:
        raise ValueError("no positive hand codes; recall undefined")
    return sum(positives) / len(positives)


def calibration_pass(kappas: dict[str, float], breach_recall: float) -> dict:
    failing = sorted(m for m, k in kappas.items() if k < KAPPA_MIN)
    recall_ok = breach_recall >= BREACH_RECALL_MIN
    return {"passed": not failing and recall_ok, "failing_measures": failing, "recall_ok": recall_ok}
