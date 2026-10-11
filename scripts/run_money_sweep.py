"""Diagnostic: does eval-awareness rise with the money level? Runs archetype 8 at each MONEY_LEVELS
value, reference cell otherwise, design v4 (ablate="quiet_factors", the locked design the full grid used).
Usage: run_money_sweep.py MODEL LOG_DIR N_PER_LEVEL [LEVELS] [FIRST]
LEVELS is a comma-separated GBP list (default: the grid's MONEY_LEVELS). FIRST (default 0) starts at run index
FIRST, so disjoint index ranges can run as parallel shards over the same seeds. Claude and Codex models run via their CLI adapters."""
import json
import re
import sys
import zlib
from pathlib import Path

from remit_cni.coding.judge import EVAL_SUSPICION_PATTERNS
from remit_cni.coding.mechanical import code_run
from remit_cni import codex_cli
from remit_cni.claude_cli import CLI_MODELS, make_cli_agent
from remit_cni.models import make_agent
from remit_cni.runner import MONEY_LEVELS, REFERENCE
from remit_cni.sandbox.harness import run_episode
from remit_cni.sandbox.logger import load_log
from remit_cni.scenarios.compiler import Factors, compile_scenario

model, root, n = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
levels = tuple(int(x) for x in sys.argv[4].split(",")) if len(sys.argv) > 4 else MONEY_LEVELS
first = int(sys.argv[5]) if len(sys.argv) > 5 else 0


def completed(path):
    try:
        log = load_log(path)
    except StopIteration:  # no final record: the run is still in progress in another shard, or was interrupted
        return None
    return log if log["final"]["error"] is None else None


agent = (make_cli_agent(model) if model in CLI_MODELS else
         codex_cli.make_codex_agent(model) if model in codex_cli.CLI_MODELS else make_agent(model))
for money in levels:
    log_dir = root / str(money)
    log_dir.mkdir(parents=True, exist_ok=True)
    done = {log["header"]["seed"] for log in map(completed, log_dir.glob("*.jsonl")) if log}
    for i in range(first, n):
        seed = zlib.crc32(f"money-sweep-{money}-{i}".encode())
        if seed in done:
            continue
        factors = {**REFERENCE, "money_gbp": money}
        s = compile_scenario(8, Factors(**factors), seed=seed, ablate="quiet_factors")  # v4: best MiMo result so far
        run_episode(agent, {**factors, "severity": "NONE"}, seed=seed, model=model, log_dir=log_dir,
                    severity=s.severity, sandbox_config=s.sandbox_config, allowed_tools=s.tools, manifest=s.manifest,
                    opening_messages=s.opening_messages, block=f"money_sweep_{money}", system_prompt=s.system_prompt)

rows = {}
for money in levels:
    logs = [log for log in map(completed, (root / str(money)).glob("*.jsonl")) if log]
    text = lambda l: " ".join(x["text"] for x in l["reasoning"])
    rows[money] = {"runs": len(logs), "breaches": sum(code_run(l)["breach"] for l in logs),
                  "aware": sum(any(re.search(p, text(l), re.I) for p in EVAL_SUSPICION_PATTERNS) for l in logs)}
print(json.dumps(rows))
