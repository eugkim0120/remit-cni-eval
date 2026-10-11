"""Claude models under test via the subscription `claude -p` CLI, isolated from Claude Code itself.

The CLI is an agent with its own tools, settings, hooks and system prompt. Every one of those would
contaminate the eval (Bash/Read could open the scoring code), so each turn runs with: no built-in tools
(--tools ""), no user/project/local settings or the hooks and plugins they enable (--setting-sources ""),
only our MCP server (--strict-mcp-config), our system prompt replacing Claude Code's (--system-prompt),
an empty temp dir as cwd, and only the run's sandbox tools pre-approved. `check_isolation` re-verifies
the CLI's own init event on every turn and fails the run if anything else is exposed.

Known differences from the OpenCode path, to report rather than hide: tool names reach the model as
`mcp__sandbox__<tool>`; reasoning is the CLI's thinking *summary* (showThinkingSummaries), not raw
thinking, since without that setting the CLI emits thinking blocks with empty text; temperature is the CLI default (1.0, same as the other models); parallel tool
calls are serialised in arrival order. Failures raise; nothing is retried.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from remit_cni.models import ModelError, _fmt, _run_tool
from remit_cni.sandbox.harness import HaltRun, ToolBox

# Full IDs, not the "haiku" alias, whose target changes between CLI versions.
CLI_MODELS = {"claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001", "claude-haiku-5-5": "claude-haiku-5-5"}
MCP_PREFIX = "mcp__sandbox__"
MAX_STEPS_PER_TURN = 12
TURN_TIMEOUT_S = 900
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TurnResult:
    session_id: str | None = None
    model: str | None = None
    init_tools: list = field(default_factory=list)
    thinking: list = field(default_factory=list)
    final: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def build_argv(prompt: str, *, system_prompt: str, cli_model: str, mcp_config: str, allowed_tools: tuple,
               resume: str | None = None) -> list[str]:
    argv = ["claude", "-p", prompt, "--model", cli_model,
            "--output-format", "stream-json", "--verbose",
            "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", mcp_config,
            "--system-prompt", system_prompt,
            "--settings", json.dumps({"showThinkingSummaries": True}), "--thinking-display", "summarized",
            "--allowedTools", ",".join(MCP_PREFIX + t for t in allowed_tools),
            "--permission-mode", "default", "--max-turns", str(MAX_STEPS_PER_TURN)]
    if resume:
        argv += ["--resume", resume]
    return argv


def parse_events(lines: Iterable[str]) -> TurnResult:
    turn = TurnResult()
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            turn.session_id, turn.model, turn.init_tools = event.get("session_id"), event.get("model"), event.get("tools", [])
        elif kind == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "thinking":
                    if not block.get("thinking"):
                        raise ModelError("CLI withheld thinking text (showThinkingSummaries off?); reasoning would be lost")
                    turn.thinking.append(block["thinking"])
        elif kind == "result":
            if event.get("is_error"):
                raise ModelError(f"claude CLI turn failed ({event.get('subtype')}): {str(event.get('result'))[:300]}")
            turn.final, turn.session_id = event.get("result"), event.get("session_id") or turn.session_id
            usage = event.get("usage", {})
            turn.input_tokens, turn.output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return turn


def check_isolation(turn: TurnResult, expected_model: str) -> None:
    foreign = [t for t in turn.init_tools if not t.startswith(MCP_PREFIX)]
    if foreign:
        raise ModelError(f"isolation broken: CLI exposed non-sandbox tools {foreign}")
    if turn.model != expected_model:
        raise ModelError(f"CLI ran {turn.model!r}, expected {expected_model!r}")


class ToolServer:
    """Unix-socket server executing the bridge's tool calls against this run's ToolBox, one at a time."""

    def __init__(self, toolbox: ToolBox, path: Path):
        self.toolbox, self.path = toolbox, Path(path)
        self.halt: HaltRun | None = None
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def __enter__(self):
        self._sock.bind(str(self.path))
        self._sock.listen()
        threading.Thread(target=self._serve, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._sock.close()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                request = json.loads(conn.makefile().readline())
                with self._lock:
                    if self.halt is not None:
                        content, halted = json.dumps({"error": "run halted"}), True
                    else:
                        try:
                            content = _run_tool(self.toolbox, {"name": request["name"],
                                                               "arguments": request["arguments"]})
                            halted = False
                        except HaltRun as err:
                            self.halt, content, halted = err, json.dumps({"error": "run halted"}), True
                conn.sendall((json.dumps({"content": content, "halted": halted}) + "\n").encode())


def _run_turn(argv: list[str], cwd: str, server: ToolServer) -> TurnResult:
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "MAX_THINKING_TOKENS": os.environ.get("MAX_THINKING_TOKENS", "8000")})
    lines = []
    timer = threading.Timer(TURN_TIMEOUT_S, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            lines.append(line)
            if server.halt is not None:
                proc.kill()
                break
        proc.wait()
    finally:
        timer.cancel()
    if server.halt is not None:
        raise server.halt
    if proc.returncode != 0 and not any('"type": "result"' in l or '"type":"result"' in l for l in lines):
        raise ModelError(f"claude CLI exited {proc.returncode}: {proc.stderr.read()[:300]}")
    return parse_events(lines)


def make_cli_agent(model: str):
    if model not in CLI_MODELS:
        raise ModelError(f"model {model!r} is not permitted; use one of {tuple(CLI_MODELS)}")

    def agent(system_prompt: str, toolbox: ToolBox) -> str | None:
        prompts = []
        if toolbox.opening_messages:
            prompts.append("\n\n".join(_fmt(m) for m in toolbox.opening_messages))
        prompts += [_fmt(t) for t in toolbox.turns]
        if not prompts:
            raise ModelError("run has no opening message or turn to send")
        with tempfile.TemporaryDirectory(prefix="remit-cli-") as work:
            mcp_config = Path(work) / "mcp.json"
            mcp_config.write_text(json.dumps({"mcpServers": {"sandbox": {
                "command": sys.executable, "args": ["-m", "remit_cni.mcp_bridge"],
                "env": {"PYTHONPATH": str(REPO_ROOT), "SANDBOX_SOCKET": str(Path(work) / "tools.sock"),
                        "SANDBOX_TOOLS": json.dumps(list(toolbox.allowed_tools))}}}}))
            cwd = Path(work) / "cwd"
            cwd.mkdir()
            final, session = None, None
            with ToolServer(toolbox, Path(work) / "tools.sock") as server:
                for prompt in prompts:
                    argv = build_argv(prompt, system_prompt=system_prompt, cli_model=CLI_MODELS[model],
                                      mcp_config=str(mcp_config), allowed_tools=toolbox.allowed_tools, resume=session)
                    turn = _run_turn(argv, str(cwd), server)
                    check_isolation(turn, model)
                    for text in turn.thinking:
                        toolbox.reasoning(text)
                    toolbox.usage(turn.input_tokens, turn.output_tokens)
                    final, session = turn.final, turn.session_id
        return final

    return agent
