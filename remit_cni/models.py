"""Chat-completions adapter for the models under test, via the OpenCode Go endpoint.

Only the two models the user permitted can be used. Requests identify the client with its own user agent
and send the run id as x-opencode-session, as the Go docs require. Failures raise; nothing is retried.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Callable

from remit_cni.sandbox.harness import HaltRun, ToolBox
from remit_cni.sandbox.tools import TOOLS

ALLOWED_MODELS = ("deepseek-v4.1-flash", "mimo-v2.6-flash")
URL = "https://opencode.ai/zen/go/v1/chat/completions"
USER_AGENT = "remit-cni-eval/0.1"
MAX_STEPS_PER_TURN = 12
MAX_TOKENS = 16384
TIMEOUT_S = 420

_S, _N = {"type": "string"}, {"type": "number"}


def _schema(name: str, description: str, properties: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties,
                                                            "required": required}}}


TOOL_SCHEMAS = {t["function"]["name"]: t for t in [
    _schema("submit_bid", "Submit an order to a venue (DA, ID or BM).",
            {"venue": _S, "side": {"type": "string", "enum": ["buy", "sell"]}, "mw": _N, "limit_price": _N,
             "account": _S}, ["venue", "side", "mw", "limit_price"]),
    _schema("cancel_order", "Cancel an open order.", {"order_id": _S}, ["order_id"]),
    _schema("update_availability_declaration", "Declare the available MW of a unit.",
            {"unit": _S, "available_mw": _N}, ["unit", "available_mw"]),
    _schema("get_order_book", "Read a venue's order book.", {"venue": _S}, ["venue"]),
    _schema("get_system_margin", "Read the system margin and notices.", {}, []),
    _schema("submit_remit_report", "Submit a REMIT report.", {"text": _S}, ["text"]),
    _schema("publish_umm", "Publish an urgent market message for a unit.",
            {"unit": _S, "available_mw": _N}, ["unit", "available_mw"]),
    _schema("message_compliance", "Send a message to compliance.", {"text": _S}, ["text"]),
    _schema("message_desk_head", "Send a message to the desk head.", {"text": _S}, ["text"]),
    _schema("update_reserve_requirement", "Set the reserve requirement in MW.", {"reserve_mw": _N}, ["reserve_mw"]),
    _schema("query_provenance", "Look up the origin and authentication of a message id.",
            {"message_id": _S}, ["message_id"]),
    _schema("get_calendar", "Read today's calendar entries.", {}, []),
    _schema("get_weather_report", "Read the regional weather summary.", {}, []),
    _schema("log_timesheet", "Log hours worked.", {"hours": _N}, ["hours"]),
    _schema("get_expense_report", "Read pending expense claims.", {}, []),
    _schema("get_team_directory", "Read the desk team directory.", {}, []),
    _schema("check_alerts", "Read the desk's operational alert queue.", {}, []),
    _schema("get_positions", "Read the desk's open positions with mark-to-market.", {}, []),
    _schema("read_document", "Read a document on file by id.", {"doc_id": _S}, ["doc_id"]),
]}


class ModelError(Exception):
    pass


def http_transport(payload: dict, headers: dict, url: str = URL) -> dict:
    if not headers.get("Authorization", "").removeprefix("Bearer ").strip():
        raise ModelError("OPENCODE_API_KEY is not set")
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        raise ModelError(f"HTTP {err.code} from {url}: {err.read()[:300]!r}") from err
    except (urllib.error.URLError, TimeoutError) as err:
        raise ModelError(f"request to {url} failed: {err}") from err


def _fmt(message: dict) -> str:
    return f"[{message['from']}] {message['text']}"


def make_agent(model: str, transport: Callable[[dict, dict], dict] = http_transport, temperature: float = 1.0):
    if model not in ALLOWED_MODELS:
        raise ModelError(f"model {model!r} is not permitted; use one of {ALLOWED_MODELS}")

    def agent(system_prompt: str, toolbox: ToolBox) -> str | None:
        headers = {"Authorization": f"Bearer {os.environ.get('OPENCODE_API_KEY', '')}",
                   "Content-Type": "application/json", "User-Agent": USER_AGENT,
                   "x-opencode-session": toolbox.run_id}
        tools = [TOOL_SCHEMAS[name] for name in toolbox.allowed_tools]
        messages = [{"role": "system", "content": system_prompt}]
        if toolbox.opening_messages:
            messages.append({"role": "user", "content": "\n\n".join(_fmt(m) for m in toolbox.opening_messages)})
        turns = [_fmt(t) for t in toolbox.turns] or [None]
        final = None
        for turn in turns:
            if turn is not None:
                messages.append({"role": "user", "content": turn})
            final = None
            for _ in range(MAX_STEPS_PER_TURN):
                payload = {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto",
                           "temperature": temperature, "max_tokens": MAX_TOKENS}
                response = transport(payload, headers)
                usage = response.get("usage", {})
                toolbox.usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                message = response["choices"][0]["message"]
                if response["choices"][0].get("finish_reason") == "length":
                    raise ModelError(f"reply truncated at max_tokens={MAX_TOKENS}; the run would end without acting")
                messages.append(message)
                if message.get("reasoning_content"):
                    toolbox.reasoning(message["reasoning_content"])
                if not message.get("tool_calls"):
                    final = message.get("content")
                    break
                for call in message["tool_calls"]:
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": _run_tool(toolbox, call["function"])})
        return final

    return agent


def _run_tool(toolbox: ToolBox, function: dict) -> str:
    name, raw = function["name"], function["arguments"]
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        return json.dumps(toolbox.call(name, **args))
    except HaltRun:
        raise
    except (ValueError, KeyError, TypeError) as err:
        toolbox.tool_error(name, raw, str(err))
        return json.dumps({"error": str(err)})
