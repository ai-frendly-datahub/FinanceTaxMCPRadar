from __future__ import annotations

import sys
from copy import deepcopy

import pytest

from radar.config_loader import load_category_config
from radar.exceptions import NetworkError
from radar.mcp_source import collect_mcp_server_source, parse_mcp_source_config
from radar.models import Source

FAKE_MCP_SERVER = r"""
import json
import sys

for raw in sys.stdin:
    message = json.loads(raw)
    method = message.get("method")
    if method == "notifications/initialized":
        continue
    request_id = message.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-finance-tax-mcp", "version": "0.0.0"},
        }
    elif method == "tools/call":
        tool_name = message["params"]["name"]
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "title": f"{tool_name} smoke result",
                            "url": "https://example.com/finance-tax-mcp-smoke",
                            "summary": "fake MCP stdio payload",
                        }
                    ),
                }
            ]
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
"""


HANGING_MCP_SERVER = "import time; time.sleep(30)"


def _ready_candidate() -> Source:
    category = load_category_config("finance_tax_mcp")
    matches = [
        source
        for source in category.sources
        if source.type == "mcp_server"
        and source.config.get("repository") == "Mrbaeksang/korea-stock-analyzer-mcp"
    ]
    assert len(matches) == 1
    return matches[0]


def test_permanently_disabled_candidate_keeps_allowlisted_command_contract() -> None:
    source = _ready_candidate()

    assert source.enabled is False
    assert source.config["activation_status"] == "permanently_disabled_runtime_unstable"
    assert source.config["runtime_timeout_confirmed_at"] == "2026-04-29T04:36:46+00:00"
    assert source.config["runtime_resolution_status"] == "permanently_disabled_runtime_unstable"
    assert source.config["disabled_reason"] == "upstream_stdio_initialize_timeout"
    assert source.config["activation_gates"] == []
    config = parse_mcp_source_config(source, timeout=10, limit=5)

    assert config.transport == "stdio"
    assert config.command == "npx"
    assert config.args == ("-y", "@mrbaeksang/korea-stock-analyzer-mcp")
    assert config.env == {}
    assert [tool.name for tool in config.tools] == ["search_news"]
    assert config.tools[0].arguments == {
        "company_name": "Samsung Electronics",
        "ticker": "005930",
        "limit": 3,
    }


def test_runtime_timeout_candidate_runs_against_fake_stdio_transport() -> None:
    source = deepcopy(_ready_candidate())
    source.config["command"] = sys.executable
    source.config["args"] = ["-c", FAKE_MCP_SERVER]
    source.config["timeout_seconds"] = 5

    articles = collect_mcp_server_source(
        source,
        category="finance_tax_mcp",
        limit=10,
        timeout=5,
    )

    assert len(articles) == 1
    assert {article.source for article in articles} == {"Mrbaeksang/korea-stock-analyzer-mcp"}
    assert {article.link for article in articles} == {"https://example.com/finance-tax-mcp-smoke"}
    assert {article.summary for article in articles} == {"fake MCP stdio payload"}
    assert articles[0].title == "search_news smoke result"


def test_stdio_runtime_timeout_reports_request_context() -> None:
    source = deepcopy(_ready_candidate())
    source.config["command"] = sys.executable
    source.config["args"] = ["-c", HANGING_MCP_SERVER]
    source.config["timeout_seconds"] = 1

    with pytest.raises(NetworkError, match="response 1 after 1s"):
        collect_mcp_server_source(
            source,
            category="finance_tax_mcp",
            limit=10,
            timeout=1,
        )
