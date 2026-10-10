import json

import pytest

from remit_cni.models import ALLOWED_MODELS, ModelError, TOOL_SCHEMAS, make_agent
from remit_cni.sandbox.harness import HaltRun, run_episode
from remit_cni.sandbox.logger import load_log
from remit_cni.sandbox.tools import TOOLS

F = {"certainty": "HIGH"}


def reply(content=None, calls=(), reasoning=None, usage=(10, 5)):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [{"id": f"c{i}", "type": "function",
                                  "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
                                 for i, (n, a) in enumerate(calls)]
    if reasoning:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message}], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}


class Scripted:
    def __init__(self, replies):
        self.replies, self.payloads, self.headers = list(replies), [], []

    def __call__(self, payload, headers):
        self.payloads.append(json.loads(json.dumps(payload)))
        self.headers.append(headers)
        return self.replies.pop(0)


def run(tmp_path, transport, model="deepseek-v4.1-flash", **kw):
    agent = make_agent(model, transport=transport)
    path = run_episode(agent, F, seed=1, model=model, log_dir=tmp_path,
                       opening_messages=[{"from": "desk", "text": "declare low"}], **kw)
    return load_log(path)


def test_every_tool_has_a_schema():
    assert set(TOOL_SCHEMAS) == set(TOOLS)


def test_only_the_two_permitted_models_are_allowed():
    assert set(ALLOWED_MODELS) == {"deepseek-v4.1-flash", "mimo-v2.6-flash"}
    for bad in ("claude-sonnet-5", "gpt-5", "codex", "deepseek-v4-flash"):
        with pytest.raises(ModelError):
            make_agent(bad, transport=Scripted([]))


def test_agent_sees_opening_messages_and_tools_are_executed_and_logged(tmp_path):
    t = Scripted([reply(calls=[("get_system_margin", {})], reasoning="thinking"), reply(content="Done.")])
    log = run(tmp_path, t)
    first = t.payloads[0]
    assert first["messages"][0]["role"] == "system"
    assert any("declare low" in m["content"] for m in first["messages"] if m["role"] == "user")
    assert first["temperature"] == 1.0 and first["model"] == "deepseek-v4.1-flash"
    assert {tool["function"]["name"] for tool in first["tools"]} == set(TOOLS)
    assert [c["tool"] for c in log["calls"]] == ["get_system_margin"]
    assert log["reasoning"][0]["text"] == "thinking"
    assert log["final"]["message"] == "Done."
    second_messages = t.payloads[1]["messages"]
    assert second_messages[-1]["role"] == "tool" and second_messages[-1]["tool_call_id"] == "c0"


def test_headers_identify_client_and_carry_stable_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    t = Scripted([reply(calls=[("get_system_margin", {})]), reply(content="ok")])
    log = run(tmp_path, t)
    assert len({h["x-opencode-session"] for h in t.headers}) == 1
    assert t.headers[0]["x-opencode-session"] == log["header"]["run_id"]
    assert t.headers[0]["User-Agent"].startswith("remit-cni-eval/")


def test_usage_is_logged(tmp_path):
    t = Scripted([reply(calls=[("get_system_margin", {})], usage=(100, 10)), reply(content="ok", usage=(150, 20))])
    log = run(tmp_path, t)
    assert log["usage"] == {"prompt_tokens": 250, "completion_tokens": 30}


def test_bad_tool_arguments_go_back_to_model_and_are_logged(tmp_path):
    t = Scripted([reply(calls=[("submit_bid", {"venue": "ZZ", "side": "buy", "mw": 1, "limit_price": 1})]),
                  reply(content="ok")])
    log = run(tmp_path, t)
    assert log["calls"] == [] and len(log["tool_errors"]) == 1
    assert "venue" in json.loads(t.payloads[1]["messages"][-1]["content"])["error"]


def test_invalid_json_arguments_go_back_to_model(tmp_path):
    t = Scripted([reply(calls=[("get_order_book", "{not json")]), reply(content="ok")])
    assert len(run(tmp_path, t)["tool_errors"]) == 1


def test_out_of_whitelist_tool_halts_run(tmp_path):
    t = Scripted([reply(calls=[("curl", {"url": "x"})])])
    agent = make_agent("mimo-v2.6-flash", transport=t)
    with pytest.raises(HaltRun):
        run_episode(agent, F, seed=1, model="mimo-v2.6-flash", log_dir=tmp_path)


def test_step_cap_stops_a_looping_agent(tmp_path):
    t = Scripted([reply(calls=[("get_system_margin", {})]) for _ in range(30)])
    log = run(tmp_path, t)
    assert len(t.payloads) == 12 and log["final"]["message"] is None


def test_multi_turn_scenario_feeds_each_turn(tmp_path):
    t = Scripted([reply(content=f"r{i}") for i in range(3)])
    agent = make_agent("deepseek-v4.1-flash", transport=t)
    path = run_episode(agent, F, seed=1, model="deepseek-v4.1-flash", log_dir=tmp_path,
                       turns=[{"from": "ops", "text": "t1"}, {"from": "ops", "text": "t2"}, {"from": "ops", "text": "t3"}])
    users = [m["content"] for m in t.payloads[-1]["messages"] if m["role"] == "user"]
    assert [("t1" in u, "t2" in u, "t3" in u) for u in users][-3:] == [(True, False, False), (False, True, False),
                                                                        (False, False, True)]
    assert load_log(path)["final"]["message"] == "r2"


def test_http_failure_is_raised_with_context():
    from remit_cni.models import http_transport

    with pytest.raises(ModelError, match="OPENCODE_API_KEY"):
        http_transport({"model": "x"}, {"Authorization": ""}, url="http://invalid.invalid")


def test_truncated_reply_is_a_harness_error_not_a_silent_end_of_run(tmp_path):
    truncated = reply(content="", reasoning="thinking...")
    truncated["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ModelError, match="truncated"):
        run(tmp_path, Scripted([truncated]))
