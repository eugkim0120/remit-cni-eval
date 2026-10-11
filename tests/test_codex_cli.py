"""Codex CLI adapter (ChatGPT-subscription OpenAI models). Never spawns the real CLI."""
import pytest

from remit_cni import codex_cli
from remit_cni.models import ModelError

DISABLED = ("shell_tool", "unified_exec", "browser_use", "computer_use", "image_generation", "apps", "plugins",
            "multi_agent", "hooks", "goals", "tool_suggest", "in_app_browser", "code_mode_host", "remote_plugin",
            "view_image", "sleep_tool")


def _argv(**kw):
    defaults = dict(cli_model="gpt-x", catalog_file="/w/catalog.json", instructions_file="/w/sys.md", cwd="/w/cwd",
                    socket_path="/w/t.sock", allowed_tools=("submit_bid", "publish_umm"))
    return codex_cli.build_argv("hello", **{**defaults, **kw})


def test_argv_isolates_from_user_config_rules_and_builtin_tools():
    argv = _argv()
    for flag in ("--strict-config", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json"):
        assert flag in argv
    assert argv[argv.index("-s") + 1] == "read-only"
    assert argv[argv.index("-C") + 1] == "/w/cwd"
    disabled = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    assert disabled >= set(DISABLED)


def test_argv_replaces_model_instructions_and_never_prompts():
    argv = _argv()
    overrides = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert 'model_instructions_file="/w/sys.md"' in overrides
    assert 'approval_policy="never"' in overrides
    assert 'web_search="disabled"' in overrides


def test_argv_wires_only_the_sandbox_mcp_server_with_allowed_tools():
    overrides = [a for a in _argv() if a.startswith("mcp_servers.")]
    assert all(o.startswith("mcp_servers.sandbox.") for o in overrides)
    assert any('SANDBOX_TOOLS = "[\\"submit_bid\\", \\"publish_umm\\"]"' in o for o in overrides)
    assert any('SANDBOX_SOCKET = "/w/t.sock"' in o for o in overrides)


def test_argv_prompt_is_last_and_model_is_pinned():
    argv = _argv()
    assert argv[-1] == "hello"
    assert argv[argv.index("-m") + 1] == "gpt-x"


def test_argv_strips_injected_context_and_extra_tools():
    """Verified with `codex debug prompt-input` and a live capture: without these the model sees Codex skills,
    a multi-agent role, permission and environment blocks, and request_user_input/update_plan tools."""
    overrides = [a for i, a in enumerate(_argv()) if i and _argv()[i - 1] == "-c"]
    for o in ('model_catalog_json="/w/catalog.json"', "skills.include_instructions=false",
              "include_environment_context=false", "include_collaboration_mode_instructions=false",
              "include_apps_instructions=false", "include_permissions_instructions=false",
              "tools.experimental_request_user_input.enabled=false", "tools.update_plan.enabled=false",
              'mcp_servers.sandbox.default_tools_approval_mode="approve"', 'model_reasoning_effort="high"'):
        assert o in overrides


def test_catalog_override_forces_direct_tools_and_no_subagents():
    raw = {"models": [{"slug": "gpt-x", "tool_mode": "code_mode_only", "multi_agent_version": "v2",
                       "experimental_supported_tools": ["clock"], "supports_search_tool": True,
                       "apply_patch_tool_type": "freeform", "context_window": 1}, {"slug": "other"}]}
    catalog = codex_cli.build_catalog(raw, "gpt-x")
    assert catalog == {"models": [{"slug": "gpt-x", "tool_mode": "direct", "multi_agent_version": None,
                                   "experimental_supported_tools": [], "supports_search_tool": False,
                                   "apply_patch_tool_type": None, "context_window": 1}]}


def test_catalog_without_the_model_is_refused():
    with pytest.raises(ModelError, match="gpt-x"):
        codex_cli.build_catalog({"models": [{"slug": "other"}]}, "gpt-x")


class _Recorder:
    def __init__(self):
        self.reasons, self.usages = [], []

    def reasoning(self, text):
        self.reasons.append(text)

    def usage(self, prompt_tokens, completion_tokens):
        self.usages.append((prompt_tokens, completion_tokens))


def _item(kind, **fields):
    return {"type": "item.completed", "item": {"id": "i", "type": kind, **fields}}


def test_turn_parser_logs_reasoning_final_and_usage():
    """Event shapes copied from a captured `codex exec --json` run of gpt-6-luna against the sandbox bridge."""
    box = _Recorder()
    parser = codex_cli.TurnParser(box)
    for event in [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
                  {"type": "item.started", "item": {"id": "i0", "type": "mcp_tool_call", "server": "sandbox",
                                                    "tool": "get_system_margin", "status": "in_progress"}},
                  _item("mcp_tool_call", server="sandbox", tool="get_system_margin", status="completed", error=None),
                  _item("reasoning", text="**Checking margin information**"),
                  _item("agent_message", text="Margin is 4,000 MW."),
                  {"type": "turn.completed", "usage": {"input_tokens": 1339, "cached_input_tokens": 0,
                                                       "output_tokens": 437, "reasoning_output_tokens": 344}}]:
        parser.feed(event)
    assert box.reasons == ["**Checking margin information**"]
    assert parser.final == "Margin is 4,000 MW."
    assert parser.tool_calls == 1
    assert parser.completed
    assert box.usages == [(1339, 437)]


@pytest.mark.parametrize("event", [
    {"type": "error", "message": "stream disconnected, retrying"},
    {"type": "turn.failed", "error": {"message": "400 model requires newer Codex"}},
    _item("error", message="Model metadata for `x` not found"),
    _item("command_execution", command="cat scoring.py"),
    _item("mcp_tool_call", server="other", tool="read", status="completed", error=None),
    _item("mcp_tool_call", server="sandbox", tool="submit_bid", status="failed",
          error={"message": "MCP tool call requires approval, but approval policy is never"}),
])
def test_turn_parser_fails_loudly_on_retries_errors_and_anything_outside_the_sandbox(event):
    with pytest.raises(ModelError):
        codex_cli.TurnParser(_Recorder()).feed(event)


def test_unknown_model_is_refused():
    with pytest.raises(ModelError):
        codex_cli.make_codex_agent("gpt-4o")
