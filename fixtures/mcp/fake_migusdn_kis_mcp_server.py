#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

_TOOL_NAMES = [
    "inquery_balance",
    "inquery_order_detail",
    "inquery_order_list",
    "inquery_overseas_stock_price",
    "inquery_stock_ask",
    "inquery_stock_history",
    "inquery_stock_info",
    "inquery_stock_price",
    "order_overseas_stock",
    "order_stock",
]


TOOLS = [
    {
        "name": tool_name,
        "title": f"migusdn KIS {tool_name}",
        "description": f"Return deterministic KIS MCP {tool_name} fixture results.",
        "inputSchema": {"type": "object", "additionalProperties": True},
    }
    for tool_name in _TOOL_NAMES
]


def _make_result(tool: str) -> dict[str, Any]:
    slug = tool.replace("_", "-")
    return {
        "title": f"KIS MCP {slug} fixture",
        "url": f"https://example.test/finance-tax/migusdn-kis/{slug}-fixture",
        "summary": f"Fixture-only KIS MCP {slug} result for collector normalization.",
        "record_id": f"fixture-kis-{slug}",
        "source": "fixture",
    }


RESULTS: dict[str, dict[str, Any]] = {tool: _make_result(tool) for tool in _TOOL_NAMES}


def write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def response_for(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "fake-migusdn-kis-mcp-server",
                    "version": "0.0.0",
                },
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        raw_params = message.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        raw_tool_name = params.get("name")
        tool_name = raw_tool_name if isinstance(raw_tool_name, str) else ""
        result = RESULTS.get(tool_name)
        if result is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Unsupported tool: {tool_name}"}],
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result,
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unsupported method: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = response_for(message)
        if response is not None:
            write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
