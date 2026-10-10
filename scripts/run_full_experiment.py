"""Phase 5 + 6: run the full block set for one model within budget, resumable, then build the report.
Usage: run_full_experiment.py MODEL LOG_DIR REPORT_DIR [CEILING_GBP] [MAX_WORKERS]

Resumable: re-running with the same LOG_DIR skips (block, seed) pairs already completed (see
runner._completed). Safe to Ctrl-C and re-invoke. Runs execute concurrently within each block
(MAX_WORKERS threads; each run is network-bound and has its own sandbox and log file, so this is safe).
"""
import json
import sys
from pathlib import Path

from remit_cni.budget import DEFAULT_CEILING_GBP, execute_within_budget
from remit_cni.models import make_agent
from remit_cni.report import build_report
from remit_cni.runner import blocks

model, log_dir, report_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
ceiling = float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_CEILING_GBP
max_workers = int(sys.argv[5]) if len(sys.argv) > 5 else 8

cells = blocks()
result = execute_within_budget(cells, make_agent(model), model=model, log_dir=log_dir, ceiling_gbp=ceiling,
                               max_workers=max_workers)
print(json.dumps(result, indent=1), flush=True)

report = build_report(log_dir, report_dir)
print(json.dumps(report, indent=1))
print(f"report written to {report_dir / 'report.md'}")
