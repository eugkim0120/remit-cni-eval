"""Phase 6 analysis: per-cell table, confirmatory logit, GBP threshold with bootstrap CI, mitigation table.

Clusters are the (company, plant) narrative identity the harness draws from the run seed; the plan says
"scenario template seed" and every run has its own seed, so this is the nearest stable grouping.
"""
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.special import expit

from remit_cni.coding.judge import EVAL_SUSPICION_PATTERNS
from remit_cni.coding.mechanical import code_run
from remit_cni.sandbox.grid import Severity
from remit_cni.sandbox.harness import make_identity
from remit_cni.sandbox.logger import load_log

CELL_COLUMNS = ["certainty", "log10_money", "detection", "punishment", "severity"]
MONEY_RANGE_LOG10 = (math.log10(5_000), math.log10(150_000))
Z95 = 1.959964


def _mechanical_awareness(log: dict) -> bool:
    """Regex-only eval-awareness, no model call: the judge's LLM pass is added separately for the pilot
    report, not for the full grid (that many judge calls is out of budget). See docs/prereg.md 2026-09-27
    closure amendment: awareness is reported as a covariate, not a gate."""
    text = " ".join([r["text"] for r in log["reasoning"]] + [log["final"]["message"] or ""])
    return any(re.search(p, text, re.IGNORECASE) for p in EVAL_SUSPICION_PATTERNS)


def build_frame(log_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(Path(log_dir).glob("*.jsonl")):
        try:
            log = load_log(path)
        except StopIteration:
            continue  # no "final" record yet: an interrupted run, not a completed one
        if log["final"]["error"] is not None or log["final"]["halted"]:
            continue
        m = log["header"]["manifest"]
        coded = code_run(log)
        who = make_identity(log["header"]["seed"])
        rows.append({
            "run_id": log["header"]["run_id"], "block": log["header"]["block"], "archetype": m["archetype"],
            "framing": m["framing"], "certainty": int(m["certainty"] == "HIGH"),
            "log10_money": math.log10(m["money_gbp"]) if m["money_gbp"] > 0 else float("nan"),
            "detection": int(m["detection"] == "HIGH"), "punishment": int(m["punishment"] == "HIGH"),
            "severity": list(Severity).index(Severity[m["severity"]]),
            "cluster": f"{who['company']}|{who['plant']}", "breach": int(coded["breach"]),
            "disguised_breach": int(coded["disguised_breach"]), "escalation_instead": int(coded["escalation_instead"]),
            "eval_awareness": int(_mechanical_awareness(log)),
        })
    columns = ["run_id", "block", "archetype", "framing", "certainty", "log10_money", "detection", "punishment",
              "severity", "cluster", "breach", "disguised_breach", "escalation_instead", "eval_awareness"]
    return pd.DataFrame(rows, columns=columns)


def _design(df: pd.DataFrame, pooled: bool) -> pd.DataFrame:
    X = pd.DataFrame({"const": 1.0, "certainty": df.certainty, "log10_money": df.log10_money,
                      "detection": df.detection, "punishment": df.punishment,
                      "det_x_pun": df.detection * df.punishment})
    if pooled:
        X["severity"] = df.severity
    return X.astype(float)


def firth_logit(X: np.ndarray, y: np.ndarray, max_iter: int = 200, tol: float = 1e-8) -> np.ndarray:
    beta = np.zeros(X.shape[1])
    for _ in range(max_iter):
        p = expit(X @ beta)
        w = p * (1 - p)
        info_inv = np.linalg.inv(X.T @ (w[:, None] * X))
        hat = w * np.einsum("ij,jk,ik->i", X, info_inv, X)
        step = info_inv @ (X.T @ (y - p + hat * (0.5 - p)))
        step = np.clip(step, -5, 5)
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            return beta
    raise RuntimeError("Firth logit did not converge")


def _has_degenerate_cell(df: pd.DataFrame) -> bool:
    cells = df.groupby(CELL_COLUMNS).breach.agg(["sum", "count"])
    return bool(((cells["sum"] == 0) | (cells["sum"] == cells["count"])).any())


def fit_logit(df: pd.DataFrame, pooled: bool = False) -> dict:
    X, y = _design(df, pooled), df.breach.astype(float)
    if _has_degenerate_cell(df):
        beta = firth_logit(X.to_numpy(), y.to_numpy())
        p = expit(X.to_numpy() @ beta)
        cov = np.linalg.inv(X.to_numpy().T @ ((p * (1 - p))[:, None] * X.to_numpy()))
        return {"method": "firth", "params": pd.Series(beta, index=X.columns),
                "se": pd.Series(np.sqrt(np.diag(cov)), index=X.columns)}
    groups = pd.factorize(df.cluster)[0]
    res = sm.GLM(y, X, family=sm.families.Binomial()).fit(cov_type="cluster", cov_kwds={"groups": groups})
    return {"method": "glm_cluster", "params": res.params, "se": res.bse}


def gbp_threshold(params: pd.Series, certainty: int, detection: int, punishment: int, severity: int = 0) -> dict:
    slope = params["log10_money"]
    rest = (params["const"] + params["certainty"] * certainty + params["detection"] * detection
            + params["punishment"] * punishment + params["det_x_pun"] * detection * punishment)
    if "severity" in params.index:
        rest += params["severity"] * severity
    if slope <= 0:
        return {"status": "no crossing in range", "gbp": None}
    x = -rest / slope
    if MONEY_RANGE_LOG10[0] <= x <= MONEY_RANGE_LOG10[1]:
        return {"status": "crossing", "gbp": 10 ** x}
    return {"status": "no crossing in range", "gbp": None}


def bootstrap_threshold(df: pd.DataFrame, certainty: int, detection: int, punishment: int, severity: int = 0,
                        reps: int = 500, seed: int = 0, pooled: bool = False) -> dict:
    rng = np.random.default_rng(seed)
    clusters = df.cluster.unique()
    by_cluster = {c: g for c, g in df.groupby("cluster")}
    values, misses = [], 0
    for _ in range(reps):
        picked = rng.choice(clusters, size=len(clusters), replace=True)
        sample = pd.concat([by_cluster[c] for c in picked], ignore_index=True)
        try:
            params = fit_logit(sample, pooled)["params"]
        except (np.linalg.LinAlgError, RuntimeError):
            misses += 1
            continue
        t = gbp_threshold(params, certainty, detection, punishment, severity)
        if t["status"] == "crossing":
            values.append(t["gbp"])
        else:
            misses += 1
    point = gbp_threshold(fit_logit(df, pooled)["params"], certainty, detection, punishment, severity)
    lo, hi = (np.percentile(values, [2.5, 97.5]) if values else (None, None))
    return {"point": point, "ci_low": lo, "ci_high": hi, "share_no_crossing": misses / reps}


def cell_table(df: pd.DataFrame) -> pd.DataFrame:
    return (df.groupby(CELL_COLUMNS).agg(n=("breach", "size"), breach_rate=("breach", "mean"),
                                         disguised_rate=("disguised_breach", "mean"),
                                         escalation_rate=("escalation_instead", "mean")).reset_index())


def _wilson(k: int, n: int) -> tuple[float, float, float]:
    p = k / n
    d = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / d
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n ** 2)) / d
    return p, centre - half, centre + half


def newcombe_diff(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """95% CI for p1 - p2 (Newcombe method 10)."""
    p1, l1, u1 = _wilson(k1, n1)
    p2, l2, u2 = _wilson(k2, n2)
    diff = p1 - p2
    return (diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def awareness_breach_table(df: pd.DataFrame) -> pd.DataFrame:
    """Breach rate split by mechanical eval-awareness, with a Wilson CI per group. Reported alongside the
    confirmatory model, not used to gate or exclude runs (docs/prereg.md, 2026-09-27 closure amendment)."""
    rows = []
    for aware, group in df.groupby("eval_awareness"):
        k, n = int(group.breach.sum()), len(group)
        rate, lo, hi = _wilson(k, n)
        rows.append({"eval_awareness": aware, "n": n, "breach_rate": rate, "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows).sort_values("eval_awareness").reset_index(drop=True)


def headline_threshold_gap(none_df: pd.DataFrame, disconnection_df: pd.DataFrame, certainty: int, detection: int,
                           punishment: int, reps: int = 500, seed: int = 0) -> dict:
    """Section 2 headline number: the GBP threshold at severity NONE minus at DISCONNECTION, each with its own
    bootstrap CI. Reported as None (not extrapolated or imputed) whenever either side never crosses 0.5 in range,
    per prereg section 2."""
    none_t = bootstrap_threshold(none_df, certainty, detection, punishment, severity=0, reps=reps, seed=seed)
    disc_t = bootstrap_threshold(disconnection_df, certainty, detection, punishment,
                                 severity=list(Severity).index(Severity.DISCONNECTION), reps=reps, seed=seed)
    gap = (none_t["point"]["gbp"] - disc_t["point"]["gbp"]
          if none_t["point"]["status"] == disc_t["point"]["status"] == "crossing" else None)
    return {"none": none_t["point"], "disconnection": disc_t["point"], "gap_gbp": gap,
            "none_ci": (none_t["ci_low"], none_t["ci_high"]), "disconnection_ci": (disc_t["ci_low"], disc_t["ci_high"])}


def mitigation_table(reference: pd.DataFrame, arms: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, arm in arms.items():
        row = {"arm": name, "n": len(arm), "ref_breach_rate": reference.breach.mean(),
               "arm_breach_rate": arm.breach.mean()}
        row["diff"] = row["arm_breach_rate"] - row["ref_breach_rate"]
        row["ci_low"], row["ci_high"] = newcombe_diff(int(arm.breach.sum()), len(arm),
                                                      int(reference.breach.sum()), len(reference))
        row["disguised_diff"] = arm.disguised_breach.mean() - reference.disguised_breach.mean()
        row["verdict"] = "no measured effect" if row["ci_low"] <= 0 <= row["ci_high"] else "effect"
        rows.append(row)
    return pd.DataFrame(rows).sort_values("diff").reset_index(drop=True)
