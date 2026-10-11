"""Stdio MCP server the Claude CLI spawns: exposes the run's allowed sandbox tools and forwards every call
over a unix socket to the ToolServer in the runner process, which owns the sandbox and the log.

Hand-rolled newline-delimited JSON-RPC rather than the `mcp` package: three methods are all the CLI uses,
and a dependency would be the largest thing in this file. Env: SANDBOX_SOCKET, SANDBOX_TOOLS (JSON list).
"""
import json
import os
import socket
import sys
from typing import Callable

from remit_cni.models import TOOL_SCHEMAS

PROTOCOL_VERSION = "2025-06-18"


def _tool_entry(name: str) -> dict:
    fn = TOOL_SCHEMAS[name]["function"]
    return {"name": name, "description": fn["description"], "inputSchema": fn["parameters"]}


def handle(request: dict, allowed_tools: tuple, call_tool: Callable[[str, dict], str]) -> dict | None:
    method, rid = request.get("method"), request.get("id")
    if rid is None:
        return None
    if method == "initialize":
        version = request.get("params", {}).get("protocolVersion", PROTOCOL_VERSION)
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "sandbox", "version": "0.1"}}
    elif method == "tools/list":
        result = {"tools": [_tool_entry(n) for n in allowed_tools]}
    elif method == "tools/call":
        params = request["params"]
        result = {"content": [{"type": "text", "text": call_tool(params["name"], params.get("arguments") or {})}],
                  "isError": False}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _forward(socket_path: str) -> Callable[[str, dict], str]:
    def call_tool(name: str, arguments: dict) -> str:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(socket_path)
            s.sendall((json.dumps({"name": name, "arguments": json.dumps(arguments)}) + "\n").encode())
            return json.loads(s.makefile().readline())["content"]
    return call_tool


def main() -> None:
    allowed = tuple(json.loads(os.environ["SANDBOX_TOOLS"]))
    call_tool = _forward(os.environ["SANDBOX_SOCKET"])
    for line in sys.stdin:
        if not line.strip():
            continue
        reply = handle(json.loads(line), allowed, call_tool)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
