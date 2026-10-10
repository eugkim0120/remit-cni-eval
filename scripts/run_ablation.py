"""Ablation probes on the most-tempting cell: which element drives eval-awareness and breach.
Usage: run_ablation.py MODEL ROOT_DIR N   (variants: baseline, no_pnl, no_docs, no_short, quiet; optional trailing names select some; resumable)"""
import json
import re
import sys
import zlib
from pathlib import Path

from remit_cni.coding.judge import EVAL_SUSPICION_PATTERNS
from remit_cni.coding.mechanical import code_run
from remit_cni.models import make_agent
from remit_cni.runner import MOST_TEMPTING
from remit_cni.sandbox.harness import run_episode
from remit_cni.sandbox.logger import load_log
from remit_cni.scenarios.compiler import Factors, compile_scenario

model, root, n = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
ALL = {"baseline": None, "no_pnl": "no_pnl", "no_docs": "no_docs", "no_short": "no_short", "quiet": "quiet",
       "quiet_factors": "quiet_factors", "quiet_dilution": "quiet_dilution", "quiet_pull": "quiet_pull",
       "quiet_plain": "quiet_plain", "quiet_v5": "quiet_v5"}
VARIANTS = {k: ALL[k] for k in (sys.argv[4:] or list(ALL))}
agent = make_agent(model)


def clean(log_dir: Path) -> list[Path]:
    return [p for p in sorted(log_dir.glob("*.jsonl")) if load_log(p)["final"]["error"] is None]


for name, ablate in VARIANTS.items():
    log_dir = root / name
    log_dir.mkdir(parents=True, exist_ok=True)
    for i in range(len(clean(log_dir)), n):
        seed = zlib.crc32(f"ablation-{name}-{i}".encode())
        s = compile_scenario(8, Factors(**MOST_TEMPTING), seed=seed, ablate=ablate)
        run_episode(agent, {**MOST_TEMPTING, "severity": "NONE"}, seed=seed, model=model, log_dir=log_dir,
                    severity=s.severity, sandbox_config=s.sandbox_config, allowed_tools=s.tools, manifest=s.manifest,
                    opening_messages=s.opening_messages, block=f"ablation_{name}", system_prompt=s.system_prompt)

rows = {}
for name in VARIANTS:
    logs = [load_log(p) for p in clean(root / name)]
    text = lambda l: " ".join([r["text"] for r in l["reasoning"]] + [l["final"]["message"] or ""])
    coded = [code_run(l) for l in logs]
    rows[name] = {"runs": len(logs), "breaches": sum(c["breach"] for c in coded),
                  "umm_published": sum(c["umm_published"] for c in coded),
                  "aware": sum(any(re.search(p, text(l), re.I) for p in EVAL_SUSPICION_PATTERNS) for l in logs)}
print(json.dumps(rows))
