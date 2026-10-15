from __future__ import annotations

import asyncio

from tools.hermes_mcp_server import mcp


def test_mcp_server_exposes_expected_tools():
    """The Hermes MCP server must expose the two TFG mission tools."""
    tools = asyncio.run(mcp.list_tools())

    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "validate_mission",
        "validate_and_export_qgc",
    }