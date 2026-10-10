"""One JSONL file per run: header, tool calls, reasoning blocks, final record."""
import json
from pathlib import Path

from remit_cni.sandbox.grid import Severity
from remit_cni.sandbox.tools import Sandbox


class RunLogger:
    def __init__(self, path: Path, header: dict):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write({"type": "header", **header})

    def _write(self, record: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def context(self, system_prompt: str, opening_messages: list) -> None:
        self._write({"type": "context", "system_prompt": system_prompt, "opening_messages": opening_messages})

    def call(self, tool: str, args: dict, result: dict, t: int) -> None:
        self._write({"type": "call", "t": t, "tool": tool, "args": args, "result": result})

    def usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self._write({"type": "usage", "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens})

    def tool_error(self, tool: str, args: object, error: str) -> None:
        self._write({"type": "tool_error", "tool": tool, "args": args, "error": error})

    def reasoning(self, text: str) -> None:
        self._write({"type": "reasoning", "text": text})

    def final(self, message: str | None, state: dict, halted: bool = False, halt_reason: str | None = None,
              error: str | None = None) -> None:
        self._write({"type": "final", "message": message, "state": state, "halted": halted,
                     "halt_reason": halt_reason, "error": error})


def load_log(path: Path) -> dict:
    records = [json.loads(line) for line in Path(path).read_text().splitlines()]
    return {
        "header": next(r for r in records if r["type"] == "header"),
        "context": next((r for r in records if r["type"] == "context"), None),
        "usage": {"prompt_tokens": sum(r["prompt_tokens"] for r in records if r["type"] == "usage"),
                  "completion_tokens": sum(r["completion_tokens"] for r in records if r["type"] == "usage")},
        "tool_errors": [r for r in records if r["type"] == "tool_error"],
        "calls": [r for r in records if r["type"] == "call"],
        "reasoning": [r for r in records if r["type"] == "reasoning"],
        "final": next(r for r in records if r["type"] == "final"),
    }


def replay(log: dict) -> dict:
    """Re-execute the logged tool calls on a fresh sandbox and return its final state."""
    header = log["header"]
    sandbox = Sandbox(seed=header["seed"], severity=Severity[header["severity"]],
                      **header.get("sandbox_config", {}))
    for call in log["calls"]:
        sandbox.call(call["tool"], **call["args"])
    return sandbox.snapshot()
