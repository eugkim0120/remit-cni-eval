"""Phase 4: run the 40-run pilot on one model, code it, apply the gate. Usage: run_pilot.py MODEL LOG_DIR [ITERATION]"""
import json
import sys
from pathlib import Path

from remit_cni.coding.judge import eval_suspicion
from remit_cni.coding.mechanical import code_run
from remit_cni.gate import pilot_gate
from remit_cni.models import ALLOWED_MODELS, http_transport, make_agent
from remit_cni.runner import blocks, execute
from remit_cni.sandbox.logger import load_log

model, log_dir = sys.argv[1], Path(sys.argv[2])
ITERATION = int(sys.argv[3]) if len(sys.argv) > 3 else 0
JUDGE_MODEL = "mimo-v2.6-flash"


def complete(prompt: str) -> str:
    payload = {"model": JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0,
               "max_tokens": 512}
    headers = {"Authorization": f"Bearer {__import__('os').environ.get('OPENCODE_API_KEY', '')}",
               "Content-Type": "application/json", "User-Agent": "remit-cni-eval/0.1",
               "x-opencode-session": "judge-pilot"}
    text = http_transport(payload, headers)["choices"][0]["message"]["content"]
    return text[text.index("{"): text.rindex("}") + 1]


cells = [c for c in blocks() if c["block"] == "pilot"]
print(execute(cells, make_agent(model), model=model, log_dir=log_dir), flush=True)

rows = []
for path in sorted(log_dir.glob("*.jsonl")):
    log = load_log(path)
    if log["final"]["error"] is not None or log["header"]["model"] != model:
        continue
    tempting = "most" if log["header"]["factors"]["money_gbp"] >= 150_000 else "least"
    rows.append({"run": path.name, "tempting": tempting, "breach": code_run(log)["breach"],
                 "eval_suspicion": eval_suspicion(log, complete),
                 "prompt_tokens": log["usage"]["prompt_tokens"], "completion_tokens": log["usage"]["completion_tokens"]})
(log_dir / "pilot_results.json").write_text(json.dumps(rows, indent=1))
print(json.dumps(pilot_gate(rows, iteration=ITERATION), indent=1))
print("runs coded:", len(rows), "tokens:", sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows))
