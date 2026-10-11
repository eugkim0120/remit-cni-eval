"""OpenAI models under test via the ChatGPT-subscription `codex exec` CLI, isolated from Codex itself.

Mirrors claude_cli: Codex is an agent with a shell, browser, apply_patch, plugins, hooks, user config and
its own system prompt, any of which would contaminate the eval. Each turn runs with user config and
rules ignored (--ignore-user-config, --ignore-rules, --strict-config so a mistyped override errors
instead of being dropped), every built-in tool feature disabled, a read-only sandbox in an empty
temp directory, our system prompt replacing Codex's (model_instructions_file), no approvals, no web
search, and only the sandbox MCP server (the same bridge and ToolServer as the Claude adapter).

Codex 0.162 also injects context no flag in the list above removes: a skills list, a multi-agent role block,
permission and environment blocks, and request_user_input/update_plan/apply_patch tools; and gpt-6-luna's
catalog entry makes the model call every tool through a JavaScript `exec` wrapper ("code mode"). Those are
switched off with include_* overrides and a one-model catalog override (`build_catalog`), all checked with
`codex debug prompt-input` and a live capture. What remains, reported as a caveat: Codex adds
list_mcp_resources/list_mcp_resource_templates/read_mcp_resource for any MCP server (they reach our bridge,
which has no resources); reasoning is OpenAI's reasoning *summary*, which is much shorter than the raw
reasoning the OpenCode models expose; the step limit counts tool calls, not model responses.

Codex retries failed requests on its own and reports each retry as an `error` event; TurnParser treats
those, and any item that is not sandbox tool use, reasoning or a message, as fatal.
"""
import functools
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from remit_cni.claude_cli import MAX_STEPS_PER_TURN, REPO_ROOT, TURN_TIMEOUT_S, ToolServer
from remit_cni.models import ModelError, _fmt
from remit_cni.sandbox.harness import ToolBox

CLI_MODELS = ("gpt-6-luna", "gpt-5.6-luna")
DISABLED_FEATURES = ("shell_tool", "unified_exec", "browser_use", "computer_use", "image_generation", "apps",
                     "plugins", "multi_agent", "hooks", "goals", "tool_suggest", "in_app_browser",
                     "code_mode_host", "remote_plugin", "view_image", "sleep_tool")
# At the catalog default (medium) gpt-6-luna emitted no reasoning summary in 4 of 4 smoke runs, which would leave
# the motive analysis empty; Haiku runs with extended thinking forced on, so Luna is pinned to high to match.
REASONING_EFFORT = "high"
CATALOG_OVERRIDES = {"tool_mode": "direct", "multi_agent_version": None, "experimental_supported_tools": [],
                     "supports_search_tool": False, "apply_patch_tool_type": None}
CONTEXT_OVERRIDES = ("skills.include_instructions=false", "include_environment_context=false",
                     "include_collaboration_mode_instructions=false", "include_apps_instructions=false",
                     "include_permissions_instructions=false", "tools.experimental_request_user_input.enabled=false",
                     "tools.update_plan.enabled=false")


def _toml(value) -> str:
    return json.dumps(value)


def build_catalog(raw: dict, slug: str) -> dict:
    entries = [m for m in raw.get("models", []) if m.get("slug") == slug]
    if len(entries) != 1:
        raise ModelError(f"Codex model catalog has {len(entries)} entries for {slug!r}; upgrade or check the CLI")
    return {"models": [{**entries[0], **CATALOG_OVERRIDES}]}


@functools.cache
def _cli_catalog() -> dict:
    out = subprocess.run(["codex", "debug", "models"], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


def build_argv(prompt: str, *, cli_model: str, catalog_file: str, instructions_file: str, cwd: str,
               socket_path: str, allowed_tools: tuple) -> list[str]:
    env = {"PYTHONPATH": str(REPO_ROOT), "SANDBOX_SOCKET": socket_path,
           "SANDBOX_TOOLS": json.dumps(list(allowed_tools))}
    argv = ["codex", "exec", "--strict-config", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--json", "-s", "read-only", "-C", cwd, "-m", cli_model]
    for feature in DISABLED_FEATURES:
        argv += ["--disable", feature]
    argv += ["-c", f"model_catalog_json={_toml(catalog_file)}"]
    for override in CONTEXT_OVERRIDES:
        argv += ["-c", override]
    argv += ["-c", f"model_instructions_file={_toml(instructions_file)}",
             "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
             "-c", 'model_reasoning_summary="detailed"', "-c", f"model_reasoning_effort={_toml(REASONING_EFFORT)}",
             "-c", f"mcp_servers.sandbox.command={_toml(sys.executable)}",
             "-c", f"mcp_servers.sandbox.args={_toml(['-m', 'remit_cni.mcp_bridge'])}",
             "-c", "mcp_servers.sandbox.env={" + ", ".join(f"{k} = {_toml(v)}" for k, v in env.items()) + "}",
             "-c", 'mcp_servers.sandbox.default_tools_approval_mode="approve"']
    return argv + [prompt]


class TurnParser:
    """Consumes `codex exec --json` events as they arrive, so reasoning is logged in order with tool calls."""

    def __init__(self, toolbox: ToolBox):
        self.toolbox = toolbox
        self.final: str | None = None
        self.tool_calls = 0
        self.completed = False

    def feed(self, event: dict) -> None:
        kind = event.get("type")
        if kind in ("error", "turn.failed"):
            raise ModelError(f"codex {kind}: {str(event.get('message') or event.get('error'))[:300]}")
        if kind == "turn.completed":
            usage = event["usage"]
            self.toolbox.usage(usage["input_tokens"], usage["output_tokens"])
            self.completed = True
        elif kind == "item.started" and event["item"]["type"] == "mcp_tool_call":
            self._check_server(event["item"])
            self.tool_calls += 1
        elif kind == "item.completed":
            self._completed_item(event["item"])

    def _completed_item(self, item: dict) -> None:
        kind = item["type"]
        if kind == "reasoning":
            self.toolbox.reasoning(item["text"])
        elif kind == "agent_message":
            self.final = item["text"]
        elif kind == "mcp_tool_call":
            self._check_server(item)
            if item.get("status") != "completed":
                raise ModelError(f"sandbox tool call {item.get('tool')!r} {item.get('status')}: {item.get('error')}")
        else:
            raise ModelError(f"isolation broken or unexpected codex item {kind!r}: {json.dumps(item)[:300]}")

    @staticmethod
    def _check_server(item: dict) -> None:
        if item.get("server") != "sandbox":
            raise ModelError(f"isolation broken: tool call to MCP server {item.get('server')!r}")


def _run_turn(argv: list[str], server: ToolServer, parser: TurnParser) -> str | None:
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timer = threading.Timer(TURN_TIMEOUT_S, proc.kill)
    timer.start()
    out_of_steps = False
    try:
        for line in proc.stdout:
            parser.feed(json.loads(line))
            if server.halt is not None:
                break
            if parser.tool_calls > MAX_STEPS_PER_TURN:
                out_of_steps = True
                break
    finally:
        proc.kill()
        proc.wait()
        timer.cancel()
    if server.halt is not None:
        raise server.halt
    if out_of_steps:
        return None  # same as the OpenCode path running out of steps: the run ends without a final message
    if not parser.completed:
        raise ModelError(f"codex exited {proc.returncode} without completing the turn: {proc.stderr.read()[-300:]}")
    return parser.final


def make_codex_agent(model: str):
    if model not in CLI_MODELS:
        raise ModelError(f"model {model!r} is not permitted; use one of {CLI_MODELS}")

    def agent(system_prompt: str, toolbox: ToolBox) -> str | None:
        if toolbox.turns:
            raise ModelError("the Codex adapter runs single-turn scenarios only")
        if not toolbox.opening_messages:
            raise ModelError("run has no opening message to send")
        prompt = "\n\n".join(_fmt(m) for m in toolbox.opening_messages)
        with tempfile.TemporaryDirectory(prefix="remit-codex-") as work:
            work = Path(work)
            (work / "catalog.json").write_text(json.dumps(build_catalog(_cli_catalog(), model)))
            (work / "instructions.md").write_text(system_prompt)
            (work / "cwd").mkdir()
            argv = build_argv(prompt, cli_model=model, catalog_file=str(work / "catalog.json"),
                              instructions_file=str(work / "instructions.md"), cwd=str(work / "cwd"),
                              socket_path=str(work / "tools.sock"), allowed_tools=toolbox.allowed_tools)
            with ToolServer(toolbox, work / "tools.sock") as server:
                return _run_turn(argv, server, TurnParser(toolbox))

    return agent
