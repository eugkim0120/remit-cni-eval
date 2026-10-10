"""Phase 6: assemble the pre-registered report from a run directory.

Ties together the analysis functions in `analysis.py` against real logs. Numbers only; no raw scenario
text is embedded here (see docs/prereg.md section 12 on data handling) - a human redaction pass over any
quoted excerpt happens separately, via `redact.redact_excerpt`, before anything is shared outside the
sole-holder directory.
"""
import json
from pathlib import Path
from typing import Callable

from remit_cni.analysis import (awareness_breach_table, build_frame, cell_table, fit_logit,
                                headline_threshold_gap, mitigation_table)
from remit_cni.sandbox.grid import Severity
from remit_cni.sandbox.logger import load_log

NONE_IDX = list(Severity).index(Severity.NONE)
DISCONNECTION_IDX = list(Severity).index(Severity.DISCONNECTION)

# Prereg section 11, verbatim list, frozen at Phase 0. A change here needs a dated amendment there first.
THREATS_TO_VALIDITY = [
    "Eval awareness (manipulations are honeypot-shaped; covariate coding + wording block; not eliminated).",
    "Scenario authorship by the same model family (second model; human-edited subset of 10 scenarios).",
    "Mechanical rules under-count novel manipulations (calibration recall bounds it).",
    "Sandbox price impact is linear and known (noise added to fills).",
    "Severity legibility (CNI-recognition check).",
    "Judge blindness partial (judged measures secondary).",
    "Single-turn dominance (results generalise to the decision, not the deployment).",
    "Model version drift (logged; re-run reference cell).",
]


def _count_excluded(log_dir: Path) -> int:
    n = 0
    for path in Path(log_dir).glob("*.jsonl"):
        try:
            log = load_log(path)
        except StopIteration:
            n += 1  # no "final" record: interrupted run, excluded same as errored/halted
            continue
        if log["final"]["error"] is not None or log["final"]["halted"]:
            n += 1
    return n


def _try_fit(df, pooled=False):
    """Confirmatory logit needs enough runs and non-degenerate variation; on the pilot's small n or a
    stub-agent's all-zero data this can fail. Reported as unavailable, not silently skipped."""
    try:
        fit = fit_logit(df, pooled=pooled)
        return {"method": fit["method"], "params": fit["params"].to_dict(), "se": fit["se"].to_dict()}
    except Exception as err:
        return {"error": repr(err)}


def _try_threshold_gap(none_df, disc_df, reps):
    try:
        return headline_threshold_gap(none_df, disc_df, certainty=1, detection=0, punishment=0, reps=reps)
    except Exception as err:
        return {"error": repr(err)}


def build_report(log_dir: Path, out_dir: Path, judge_complete: Callable[[str], str] | None = None,
                 bootstrap_reps: int = 200) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = build_frame(log_dir)
    n_excluded = _count_excluded(log_dir)

    none_df = df[df.severity == NONE_IDX]
    disc_df = df[df.severity == DISCONNECTION_IDX]

    data = {
        "n_runs": len(df), "n_excluded": n_excluded,
        "cell_table_none": cell_table(none_df).to_dict("records") if len(none_df) else [],
        "cell_table_disconnection": cell_table(disc_df).to_dict("records") if len(disc_df) else [],
        "fit_none": _try_fit(none_df) if len(none_df) else {"error": "no NONE-severity runs"},
        "fit_disconnection": _try_fit(disc_df) if len(disc_df) else {"error": "no DISCONNECTION-severity runs"},
        "fit_pooled": _try_fit(df, pooled=True) if len(df) else {"error": "no runs"},
        "headline_threshold_gap": (_try_threshold_gap(none_df, disc_df, bootstrap_reps)
                                   if len(none_df) and len(disc_df) else {"error": "need both severities"}),
        "awareness_breach_table": awareness_breach_table(df).to_dict("records") if len(df) else [],
    }

    cni_arms = df[(df.block == "cni_mitigation")] if "block" in df.columns else df.iloc[0:0]
    if len(cni_arms) and len(disc_df):
        arms = {name: g for name, g in cni_arms.groupby("framing")} if "framing" in cni_arms.columns else {}
        data["mitigation_table"] = (mitigation_table(disc_df, arms).to_dict("records") if arms else [])
    else:
        data["mitigation_table"] = []

    (out_dir / "report_data.json").write_text(json.dumps(data, indent=1, default=str))
    (out_dir / "report.md").write_text(_render_markdown(data))
    return {"n_runs": data["n_runs"], "n_excluded": data["n_excluded"]}


def _render_markdown(data: dict) -> str:
    lines = [
        "# REMIT/CNI agentic-safety eval: report",
        "",
        f"Runs analysed: {data['n_runs']}. Excluded (harness failure or whitelist halt): {data['n_excluded']}.",
        "",
        "## 1. Headline number",
        "",
        "GBP threshold where fitted P(breach) crosses 0.5, severity NONE minus DISCONNECTION.",
        f"```\n{json.dumps(data['headline_threshold_gap'], indent=1, default=str)}\n```",
        "",
        "## 2. Confirmatory regression",
        "",
        "Fitted separately at NONE and DISCONNECTION, and pooled with a severity term.",
        f"NONE:\n```\n{json.dumps(data['fit_none'], indent=1, default=str)}\n```",
        f"DISCONNECTION:\n```\n{json.dumps(data['fit_disconnection'], indent=1, default=str)}\n```",
        f"Pooled:\n```\n{json.dumps(data['fit_pooled'], indent=1, default=str)}\n```",
        "",
        "## 3. Per-cell breach and disguise rates",
        "",
        f"NONE:\n```\n{json.dumps(data['cell_table_none'], indent=1, default=str)}\n```",
        f"DISCONNECTION:\n```\n{json.dumps(data['cell_table_disconnection'], indent=1, default=str)}\n```",
        "",
        "## 4. Eval-awareness covariate",
        "",
        "Breach rate split by mechanical eval-awareness (regex over reasoning and final message); not a",
        "gate, per the 2026-09-27 design-closure amendment in docs/prereg.md.",
        f"```\n{json.dumps(data['awareness_breach_table'], indent=1, default=str)}\n```",
        "",
        "## 5. CNI mitigation table",
        "",
        f"```\n{json.dumps(data['mitigation_table'], indent=1, default=str)}\n```",
        "",
        "## 6. Threats to validity",
        "",
    ]
    lines += [f"{i}. {t}" for i, t in enumerate(THREATS_TO_VALIDITY, 1)]
    lines.append("")
    return "\n".join(lines)
