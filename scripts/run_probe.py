"""Small probe: N runs of the most-tempting pilot cell, coded mechanically. Usage: run_probe.py MODEL LOG_DIR N"""
import json
import sys
from collections import Counter
from pathlib import Path

from remit_cni.coding.mechanical import code_run
from remit_cni.models import make_agent
from remit_cni.runner import blocks, execute
from remit_cni.sandbox.logger import load_log

model, log_dir, n = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
log_dir.mkdir(parents=True, exist_ok=True)
cell = next(c for c in blocks() if c["block"] == "pilot" and c.get("tempting") == "most")
print(execute([{**cell, "n": n}], make_agent(model), model=model, log_dir=log_dir), flush=True)

rules, breaches, total, tokens = Counter(), 0, 0, 0
for path in sorted(log_dir.glob("*.jsonl")):
    log = load_log(path)
    if log["final"]["error"] is not None:
        continue
    coded = code_run(log)
    total += 1
    breaches += coded["breach"]
    rules.update(coded["breach_rules"])
    tokens += log["usage"]["prompt_tokens"] + log["usage"]["completion_tokens"]
print(json.dumps({"runs": total, "breaches": breaches, "rules": dict(rules), "tokens": tokens}))
