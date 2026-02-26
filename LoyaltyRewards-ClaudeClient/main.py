"""
main.py  –  LoyaltyRewards Claude Client
─────────────────────────────────────────
FastAPI application that exposes:

  POST /api/chat          – single-turn JSON chat (full response)
  POST /api/chat/stream   – Server-Sent Events streaming chat
  GET  /api/health        – liveness + MCP server reachability
  GET  /                  – interactive web chat UI
"""

from __future__ import annotations

import json
import os
import uuid
from typing import AsyncIterator

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent import run_agent
from mcp_client import list_anthropic_tools, ping_mcp_server

# ──────────────────────────────────────────────────────────────────────────────
# Application setup
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="LoyaltyRewards Claude Client",
    description="AI-powered loyalty rewards assistant backed by an MCP tool server",
    version="1.0.0",
)

templates = Jinja2Templates(directory="templates")

# In-memory session store  {session_id: list[message]}
# For production, replace with Redis or a persistent store.
SESSIONS: dict[str, list[dict]] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # omit to start a new session


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tool_calls_made: int


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the web chat UI."""
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/health")
async def health():
    """Liveness + MCP server reachability check."""
    mcp_ok = await ping_mcp_server()
    return {
        "status": "ok",
        "mcp_server_reachable": mcp_ok,
        "active_sessions": len(SESSIONS),
    }


@app.get("/api/tools")
async def get_tools():
    """Expose the list of MCP tools discovered from the server."""
    tools = await list_anthropic_tools()
    return {"tools": tools, "count": len(tools)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """
    Non-streaming chat endpoint.

    The full agentic loop (potentially multiple Claude + MCP tool rounds)
    completes before the response is returned.
    """
    session_id = body.session_id or str(uuid.uuid4())
    history = SESSIONS.get(session_id, [])

    history.append({"role": "user", "content": body.message})

    reply, updated_history = await run_agent(history)

    # Count how many tool-result messages were added (each = 1 tool round)
    tool_rounds = sum(
        1
        for m in updated_history[len(history):]
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"]
        and m["content"][0].get("type") == "tool_result"
    )

    SESSIONS[session_id] = updated_history

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        tool_calls_made=tool_rounds,
    )


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    """
    Server-Sent Events streaming chat endpoint.

    Emits SSE events:
      data: {"type": "token",   "content": "..."}  — text chunk
      data: {"type": "tool",    "name": "...", "input": {...}}  — tool invoked
      data: {"type": "done",    "session_id": "..."}  — stream complete
      data: {"type": "error",   "content": "..."}  — error occurred
    """
    session_id = body.session_id or str(uuid.uuid4())

    async def event_stream() -> AsyncIterator[str]:
        history = SESSIONS.get(session_id, [])
        history.append({"role": "user", "content": body.message})

        try:
            reply, updated_history = await run_agent(history)
            SESSIONS[session_id] = updated_history

            # Emit the full reply as a single token event for simplicity
            # (swap for true streaming once Anthropic streaming + MCP is stable)
            yield f"data: {json.dumps({'type': 'token', 'content': reply})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/sessions/{session_id}")
async def clear_session(session_id: str):
    """Reset a conversation session."""
    SESSIONS.pop(session_id, None)
    return {"session_id": session_id, "status": "cleared"}
