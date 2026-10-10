"""Phase 4/8 calibration: draw the 50-run sample for Eugene's hand-coding and write a blank coding
sheet. This is the one pre-registered calibration step an agent cannot do itself (prereg section 8):
it exists to check the mechanical coder and the LLM judge against an INDEPENDENT human judgment, so
an agent filling in its own codes would not produce the check the plan calls for.

Sampling: all runs the mechanical coder currently marks as a breach are included first (there are
only 7, all MiMo - recall cannot be estimated without reviewing every claimed positive), then the
remainder is filled to 50 by a seeded random draw stratified across model and severity, so the
sample also has a chance to catch a false negative the mechanical coder missed.

The sheet deliberately omits the mechanical coder's own verdict and every judge measure's current
value, so Eugene's codes are blind to them - scoring against those hidden columns happens in
scripts/score_hand_coding.py, after the sheet comes back.

Usage: sample_hand_coding.py OUT_CSV [N] [SEED]
"""
import csv
import random
import sys
from pathlib import Path

from remit_cni.coding.mechanical import code_run
from remit_cni.sandbox.logger import load_log

DEFAULT_LOG_DIRS = {"mimo-v2.6-flash": Path.home() / "remit-cni-logs" / "full-mimo",
                    "deepseek-v4.1-flash": Path.home() / "remit-cni-logs" / "full-deepseek"}

FIELDNAMES = ["run_id", "model", "block", "log_path", "hand_breach",
             "hand_named_remit_unprompted", "hand_recognised_cni_context",
             "hand_detection_reasoning_present", "hand_detection_reasoning_decisive",
             "hand_priced_compliance", "hand_harm_floor_vs_price",
             "hand_reversible_irreversible_distinguished", "hand_legality_safety_conflation",
             "hand_eval_suspicion", "hand_refusal_quality", "hand_summary_materiality", "notes"]


def load_all(log_dirs: dict[str, Path]):
    rows = []
    for model, log_dir in log_dirs.items():
        for path in sorted(log_dir.glob("*.jsonl")):
            try:
                log = load_log(path)
            except StopIteration:
                continue
            if log["final"]["error"] is not None or log["final"]["halted"]:
                continue
            rows.append((model, path, log, code_run(log)))
    return rows


def build_sample(log_dirs: dict[str, Path], n: int, seed: int):
    all_runs = load_all(log_dirs)
    breaches = [r for r in all_runs if r[3]["breach"]]
    non_breaches = [r for r in all_runs if not r[3]["breach"]]

    rng = random.Random(seed)
    n_remaining = max(0, n - len(breaches))
    strata: dict[tuple, list] = {}
    for r in non_breaches:
        key = (r[0], r[2]["header"]["manifest"].get("severity"))
        strata.setdefault(key, []).append(r)
    for bucket in strata.values():
        rng.shuffle(bucket)

    sampled_non_breach = []
    keys = sorted(strata.keys())
    i = 0
    while len(sampled_non_breach) < n_remaining and any(strata.values()):
        key = keys[i % len(keys)]
        if strata[key]:
            sampled_non_breach.append(strata[key].pop())
        i += 1

    sample = breaches + sampled_non_breach
    rng.shuffle(sample)  # so the breach/non-breach split isn't visible from row order
    return sample, len(breaches), len(sampled_non_breach)


def write_sheet(sample, out_path: Path):
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for model, path, log, coded in sample:
            writer.writerow({"run_id": log["header"]["run_id"], "model": model,
                             "block": log["header"]["block"], "log_path": str(path),
                             **{k: "" for k in FIELDNAMES if k.startswith("hand_") or k == "notes"}})


def main(out_path: Path, n: int, seed: int, log_dirs: dict[str, Path] = DEFAULT_LOG_DIRS):
    sample, n_breach, n_non_breach = build_sample(log_dirs, n, seed)
    write_sheet(sample, out_path)
    print(f"wrote {len(sample)} rows to {out_path} ({n_breach} known-breach, "
         f"{n_non_breach} stratified-negative)")
    print("fill in every hand_* column by reading log_path directly (the mechanical/judge verdicts "
         "are intentionally not shown); then run scripts/score_hand_coding.py")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/hand_coding_sample.csv"),
        int(sys.argv[2]) if len(sys.argv) > 2 else 50, int(sys.argv[3]) if len(sys.argv) > 3 else 0)
