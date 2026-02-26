"""
agent.py
────────
Agentic loop that drives Claude claude-sonnet-4-6 with MCP tools.

Flow per user turn
  1. Append user message to conversation history.
  2. Call Claude with the full history + available tools.
  3. If Claude returns tool_use blocks → execute each via MCP, append
     the assistant + tool_result messages, then loop back to step 2.
  4. When Claude returns a stop_reason of "end_turn" with only text
     content, yield the final assistant reply.
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

import anthropic

from mcp_client import call_tool, list_anthropic_tools

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
MODEL: str = "claude-sonnet-4-6"
MAX_TOKENS: int = 4096
MAX_TOOL_ROUNDS: int = 10  # guard against infinite loops

SYSTEM_PROMPT = """You are a knowledgeable Loyalty Rewards assistant with full access to the
LoyaltyRewards platform via a suite of MCP tools.

Your capabilities
─────────────────
• Register new customers
• Look up any customer's points balance, tier, and redeemable cash
• Award points when a customer makes a purchase  (1 pt per $1 spent)
• Redeem rewards in 1,000-point blocks ($10 store cash each)
• List all customers
• Retrieve a customer's full transaction history

Business rules to keep in mind
────────────────────────────────
• Minimum redemption: 1,000 points → $10.00 store cash
• Tiers: Bronze (0+) · Silver (2,000+) · Gold (5,000+) · Platinum (10,000+)
• Tier upgrades are automatic, based on cumulative lifetime points earned

Behavioural guidelines
──────────────────────
• Always confirm important actions (e.g. redemptions) before executing them
  unless the user has already confirmed.
• Present monetary values with two decimal places and currency symbols.
• When displaying balances, include both the raw points total and the
  equivalent redeemable cash value.
• If a requested action would fail (e.g. insufficient points), explain why
  and suggest next steps.
• Be concise but friendly; format tabular data as Markdown tables where useful."""

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


async def run_agent(
    conversation: list[dict],
) -> tuple[str, list[dict]]:
    """
    Run one complete agentic turn (potentially multiple Claude calls).

    Parameters
    ----------
    conversation : list[dict]
        The full message history including the latest user message.
        Each element is a dict conforming to the Anthropic messages API.

    Returns
    -------
    reply : str
        The final plain-text response from Claude.
    updated_conversation : list[dict]
        The conversation with all intermediate assistant / tool messages appended.
    """
    tools = await list_anthropic_tools()
    messages = list(conversation)  # shallow copy — we'll mutate locally

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        # Collect text and tool-use blocks from this response
        text_parts: list[str] = []
        tool_uses: list[dict] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": response.content})

        if not tool_uses:
            # No tools requested → we have the final answer
            return "\n".join(text_parts), messages

        # Execute all tool calls and build a single user (tool_result) message
        tool_results: list[dict] = []
        for tu in tool_uses:
            try:
                result_text = await call_tool(tu["name"], tu["input"])
            except Exception as exc:
                result_text = f"ERROR executing {tu['name']}: {exc}"

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    # Safety fallback if we hit the round limit
    return (
        "I've reached the maximum number of tool-call rounds. "
        "Please try rephrasing your request.",
        messages,
    )
