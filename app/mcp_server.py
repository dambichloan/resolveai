"""Điểm vào MCP tối giản (JSON-RPC 2.0): initialize, tools/list, tools/call. Bật bằng MCP_ENABLED=1.
Dùng chung ToolRegistry với Agent nên cùng Execution Guard. Mỗi lệnh gọi là một lượt độc lập, không có trạng thái phiên."""
from __future__ import annotations

import json
from typing import Any

from .tools import SPEC_BY_NAME, TOOL_SPECS, ToolRegistry, Turn

PROTOCOL_VERSION = "2025-03-26"


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg: Any, registry: ToolRegistry) -> dict | None:
    """Trả về phản hồi JSON-RPC, hoặc None với thông báo (notification) không cần trả lời."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None
    if method == "initialize":
        return _ok(rid, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "resolveai-tools", "version": "1.0"}})
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": TOOL_SPECS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in SPEC_BY_NAME:
            return _err(rid, -32602, "Unknown tool")
        result = registry.call(name, args, Turn(state={}))
        return _ok(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                         "isError": "error" in result})
    return _err(rid, -32601, "Method not found")
