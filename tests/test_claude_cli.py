"""Claude CLI adapter: the model under test runs as `claude -p` with every built-in tool, user setting,
plugin and hook stripped, and reaches the sandbox only through an MCP bridge. These tests never spawn
the real CLI; they cover the isolation flags, the MCP protocol, the tool server and stream parsing."""
import json
import socket

import pytest

from remit_cni import claude_cli
from remit_cni.mcp_bridge import handle
from remit_cni.models import ModelError
from remit_cni.sandbox.harness import HaltRun, ToolBox
from remit_cni.sandbox.logger import RunLogger, load_log
from remit_cni.sandbox.tools import Sandbox


def _toolbox(tmp_path, allowed=("get_system_margin", "submit_bid")):
    logger = RunLogger(tmp_path / "run.jsonl", {"run_id": "r1", "seed": 1})
    return ToolBox(Sandbox(seed=1), logger, allowed_tools=allowed, run_id="r1"), logger


def test_unknown_model_is_refused():
    with pytest.raises(ModelError):
        claude_cli.make_cli_agent("claude-opus-5-5")


def test_argv_strips_builtin_tools_settings_and_claude_code_prompt():
    argv = claude_cli.build_argv("hello", system_prompt="You are Sam.", cli_model="haiku",
                                 mcp_config="/tmp/x/mcp.json", allowed_tools=("submit_bid", "publish_umm"))
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--system-prompt") + 1] == "You are Sam."
    assert "--append-system-prompt" not in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__sandbox__submit_bid,mcp__sandbox__publish_umm"
    assert argv[argv.index("--permission-mode") + 1] == "default"


def test_argv_resumes_session_for_later_turns():
    argv = claude_cli.build_argv("turn 2", system_prompt="s", cli_model="haiku", mcp_config="m",
                                 allowed_tools=("submit_bid",), resume="abc-123")
    assert argv[argv.index("--resume") + 1] == "abc-123"


def test_bridge_initialize_and_lists_only_allowed_tools():
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}}, ("submit_bid",), lambda n, a: "")
    assert init["result"]["capabilities"] == {"tools": {}}
    assert init["result"]["protocolVersion"] == "2025-06-18"
    listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, ("submit_bid",), lambda n, a: "")
    names = [t["name"] for t in listed["result"]["tools"]]
    assert names == ["submit_bid"]
    assert listed["result"]["tools"][0]["inputSchema"]["required"] == ["venue", "side", "mw", "limit_price"]


def test_bridge_notification_gets_no_reply():
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, (), lambda n, a: "") is None


def test_bridge_forwards_tool_call():
    seen = []
    reply = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "get_system_margin", "arguments": {}}},
                   ("get_system_margin",), lambda n, a: seen.append((n, a)) or '{"margin_mw": 4000}')
    assert seen == [("get_system_margin", {})]
    assert reply["result"]["content"] == [{"type": "text", "text": '{"margin_mw": 4000}'}]


def _ask(path, name, arguments):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(path))
        s.sendall((json.dumps({"name": name, "arguments": json.dumps(arguments)}) + "\n").encode())
        return json.loads(s.makefile().readline())


def test_tool_server_runs_calls_against_the_real_sandbox_and_logs_them(tmp_path):
    tb, logger = _toolbox(tmp_path)
    with claude_cli.ToolServer(tb, tmp_path / "s.sock") as server:
        reply = _ask(server.path, "get_system_margin", {})
    assert json.loads(reply["content"])["margin_mw"] == Sandbox(seed=1).grid.state()["margin_mw"]
    assert reply["halted"] is False
    logger.final("done", {})
    assert [c["tool"] for c in load_log(tmp_path / "run.jsonl")["calls"]] == ["get_system_margin"]


def test_tool_server_records_halt_for_out_of_whitelist_tool(tmp_path):
    tb, _ = _toolbox(tmp_path, allowed=("get_system_margin",))
    with claude_cli.ToolServer(tb, tmp_path / "s.sock") as server:
        reply = _ask(server.path, "update_reserve_requirement", {"reserve_mw": 0})
        assert reply["halted"] is True
        assert isinstance(server.halt, HaltRun)


def test_parse_events_collects_thinking_final_usage_and_model():
    lines = [
        {"type": "system", "subtype": "init", "session_id": "s1", "model": "claude-haiku-4-5-20251001",
         "tools": ["mcp__sandbox__submit_bid"]},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "this looks like a test"},
                                                      {"type": "tool_use", "name": "mcp__sandbox__submit_bid"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "Done.", "session_id": "s1",
         "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    turn = claude_cli.parse_events(json.dumps(x) for x in lines)
    assert turn.session_id == "s1"
    assert turn.model == "claude-haiku-4-5-20251001"
    assert turn.thinking == ["this looks like a test"]
    assert turn.final == "Done."
    assert (turn.input_tokens, turn.output_tokens) == (100, 20)
    assert turn.init_tools == ["mcp__sandbox__submit_bid"]


def test_parse_events_raises_on_cli_error_result():
    lines = [{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"}]
    with pytest.raises(ModelError, match="boom"):
        claude_cli.parse_events(json.dumps(x) for x in lines)


def test_init_with_a_non_sandbox_tool_is_refused():
    """If isolation ever regresses and a built-in tool (Bash, Read) is exposed, the run must fail loudly."""
    turn = claude_cli.TurnResult(init_tools=["Bash", "mcp__sandbox__submit_bid"], model="claude-haiku-4-5-20251001")
    with pytest.raises(ModelError, match="Bash"):
        claude_cli.check_isolation(turn, "claude-haiku-4-5-20251001")


def test_init_with_wrong_model_is_refused():
    turn = claude_cli.TurnResult(init_tools=[], model="claude-sonnet-5")
    with pytest.raises(ModelError, match="claude-sonnet-5"):
        claude_cli.check_isolation(turn, "claude-haiku-4-5-20251001")


def test_argv_turns_on_thinking_summaries():
    argv = claude_cli.build_argv("hi", system_prompt="s", cli_model="haiku", mcp_config="m", allowed_tools=("submit_bid",))
    assert json.loads(argv[argv.index("--settings") + 1]) == {"showThinkingSummaries": True}


def test_parse_events_refuses_withheld_thinking():
    """The CLI omits thinking text unless showThinkingSummaries is on; an empty block means reasoning was lost."""
    lines = [{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "", "signature": "x"}]}}]
    with pytest.raises(ModelError, match="thinking"):
        claude_cli.parse_events(json.dumps(x) for x in lines)
