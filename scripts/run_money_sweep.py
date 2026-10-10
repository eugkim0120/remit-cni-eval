"""Diagnostic: does eval-awareness rise with the money level? Runs archetype 8 at each MONEY_LEVELS
value, reference cell otherwise, quiet_v5 design. Usage: run_money_sweep.py MODEL LOG_DIR N_PER_LEVEL"""
import json
import re
import sys
import zlib
from pathlib import Path

from remit_cni.coding.judge import EVAL_SUSPICION_PATTERNS
from remit_cni.coding.mechanical import code_run
from remit_cni.models import make_agent
from remit_cni.runner import MONEY_LEVELS, REFERENCE
from remit_cni.sandbox.harness import run_episode
from remit_cni.sandbox.logger import load_log
from remit_cni.scenarios.compiler import Factors, compile_scenario

model, root, n = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
agent = make_agent(model)
for money in MONEY_LEVELS:
    log_dir = root / str(money)
    log_dir.mkdir(parents=True, exist_ok=True)
    done = {load_log(p)["header"]["seed"] for p in log_dir.glob("*.jsonl") if load_log(p)["final"]["error"] is None}
    for i in range(n):
        seed = zlib.crc32(f"money-sweep-{money}-{i}".encode())
        if seed in done:
            continue
        factors = {**REFERENCE, "money_gbp": money}
        s = compile_scenario(8, Factors(**factors), seed=seed, ablate="quiet_factors")  # v4: best MiMo result so far
        run_episode(agent, {**factors, "severity": "NONE"}, seed=seed, model=model, log_dir=log_dir,
                    severity=s.severity, sandbox_config=s.sandbox_config, allowed_tools=s.tools, manifest=s.manifest,
                    opening_messages=s.opening_messages, block=f"money_sweep_{money}", system_prompt=s.system_prompt)

rows = {}
for money in MONEY_LEVELS:
    logs = [load_log(p) for p in (root / str(money)).glob("*.jsonl") if load_log(p)["final"]["error"] is None]
    text = lambda l: " ".join(x["text"] for x in l["reasoning"])
    rows[money] = {"runs": len(logs), "breaches": sum(code_run(l)["breach"] for l in logs),
                  "aware": sum(any(re.search(p, text(l), re.I) for p in EVAL_SUSPICION_PATTERNS) for l in logs)}
print(json.dumps(rows))
