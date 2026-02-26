"""
mcp_client.py
─────────────
Thin async wrapper around the MCP SSE transport.

Responsibilities
  • Discover tools exposed by LoyaltyRewards-MCPServer
  • Convert MCP tool schemas → Anthropic SDK tool format
  • Execute tool calls and return plain-text results back to the agentic loop
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client


MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
MCP_SSE_URL: str = f"{MCP_SERVER_URL}/mcp/sse"


# ──────────────────────────────────────────────────────────────────────────────
# Tool discovery
# ──────────────────────────────────────────────────────────────────────────────

async def list_anthropic_tools() -> list[dict]:
    """
    Connect to the MCP server, list all tools, and convert each to the
    Anthropic SDK tool-input format:

      {
        "name": "...",
        "description": "...",
        "input_schema": { "type": "object", "properties": {...}, "required": [...] }
      }
    """
    async with sse_client(MCP_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    tools: list[dict] = []
    for t in result.tools:
        schema = t.inputSchema if t.inputSchema else {"type": "object", "properties": {}}
        tools.append(
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": schema,
            }
        )
    return tools


# ──────────────────────────────────────────────────────────────────────────────
# Tool execution
# ──────────────────────────────────────────────────────────────────────────────

async def call_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """
    Execute a single MCP tool and return the result as a UTF-8 string
    suitable for the Anthropic tool_result content block.
    """
    async with sse_client(MCP_SSE_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, tool_input)

    # Flatten content blocks → plain string
    parts: list[str] = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        else:
            parts.append(json.dumps(block, default=str))

    return "\n".join(parts) if parts else "(empty response)"


# ──────────────────────────────────────────────────────────────────────────────
# Health probe (used by the API layer)
# ──────────────────────────────────────────────────────────────────────────────

async def ping_mcp_server() -> bool:
    """Return True if the MCP server's /health endpoint responds 200."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MCP_SERVER_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False
