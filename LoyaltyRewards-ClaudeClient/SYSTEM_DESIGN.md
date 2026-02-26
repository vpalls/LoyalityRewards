# System Design — Loyalty Rewards AI Platform

> **Version:** 2.0 (Claude AI Integration)
> **Last updated:** February 2026

---

## 1. Executive Summary

The Loyalty Rewards platform is a three-tier microservice system that exposes a points-and-rewards engine via both a REST API and the Model Context Protocol (MCP). A Claude claude-sonnet-4-6 AI layer wraps the MCP interface, enabling operators to manage the entire rewards programme through natural-language conversations rather than raw API calls.

---

## 2. System Overview

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                        External Interfaces                           │
  │                                                                      │
  │   Browser / curl          Browser / AI Agent        Claude.ai       │
  │        │                         │                      │           │
  │        ▼                         ▼                      │           │
  │  ┌───────────┐          ┌──────────────────┐            │           │
  │  │  Testing  │          │  Claude AI Chat  │            │           │
  │  │  Dashboard│          │  Port 8002       │            │           │
  │  │  Port 8001│          │  (ClaudeClient)  │            │           │
  │  └─────┬─────┘          └────────┬─────────┘            │           │
  │        │  REST /api/*            │  MCP SSE             │  MCP SSE  │
  │        │                         │                      │           │
  │        └──────────┬──────────────┘──────────────────────┘           │
  │                   ▼                                                  │
  │        ┌──────────────────────┐                                     │
  │        │  MCPServer Port 8000 │                                     │
  │        │  FastMCP + FastAPI   │                                     │
  │        │  + SQLite            │                                     │
  │        └──────────────────────┘                                     │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Architecture

### 3.1 LoyaltyRewards-MCPServer (Port 8000)

**Responsibilities:** Core business logic, data persistence, dual-protocol exposure.

```
┌─────────────────────────────────────────────┐
│               FastAPI Application            │
│                                             │
│  ┌─────────────┐    ┌──────────────────┐   │
│  │   FastMCP   │    │   REST API       │   │
│  │             │    │   /api/*         │   │
│  │  /mcp/sse   │    │                  │   │
│  │  (SSE trans)│    │  • /customers    │   │
│  │             │    │  • /rewards      │   │
│  │  7 tools    │    │                  │   │
│  └──────┬──────┘    └───────┬──────────┘   │
│         │                   │              │
│         └──────────┬────────┘              │
│                    ▼                       │
│           ┌────────────────┐               │
│           │   database.py  │               │
│           │   (business    │               │
│           │    logic)      │               │
│           └───────┬────────┘               │
│                   ▼                        │
│           ┌────────────────┐               │
│           │ SQLite + WAL   │               │
│           │ /data/loyalty  │               │
│           │ .db (volume)   │               │
│           └────────────────┘               │
└─────────────────────────────────────────────┘
```

**Data model:**

```sql
customers   (id UUID PK, name, email UNIQUE, tier, created_at)
ledger      (id UUID PK, customer_id FK, type ENUM, points, description, created_at)
```

The ledger is append-only. Current balance = SUM of all earn entries minus SUM of all redeem entries. Tier is derived from cumulative earn-only points.

---

### 3.2 LoyaltyRewards-ClaudeClient (Port 8002) ✨ NEW

**Responsibilities:** LLM orchestration, agentic tool-use loop, chat session management, web UI.

```
┌──────────────────────────────────────────────────────┐
│               FastAPI Application                     │
│                                                      │
│  ┌────────────────┐   ┌──────────────────────────┐  │
│  │  Web UI        │   │  Chat API                │  │
│  │  GET /         │   │  POST /api/chat          │  │
│  │  (chat.html)   │   │  POST /api/chat/stream   │  │
│  └────────────────┘   └────────────┬─────────────┘  │
│                                    │                 │
│                         ┌──────────▼──────────┐      │
│                         │     agent.py         │      │
│                         │  run_agent()         │      │
│                         │                      │      │
│                         │  1. list_tools()     │      │
│                         │  2. claude.messages  │      │
│                         │     .create()        │      │
│                         │  3. if tool_use:     │      │
│                         │       call_tool()    │      │
│                         │       loop           │      │
│                         │  4. return reply     │      │
│                         └──────────┬──────────┘      │
│                                    │                 │
│                    ┌───────────────┼───────────┐     │
│                    ▼               ▼           ▼     │
│          ┌──────────────┐  ┌──────────┐  ┌────────┐ │
│          │ mcp_client.py│  │Anthropic │  │Session │ │
│          │              │  │Python SDK│  │Store   │ │
│          │ • list_tools │  │          │  │(dict)  │ │
│          │ • call_tool  │  │Claude    │  │        │ │
│          │ • ping       │  │claude-sonnet-4-6  │  │        │ │
│          └──────┬───────┘  └──────────┘  └────────┘ │
└─────────────────┼────────────────────────────────────┘
                  │ MCP SSE
                  ▼
        LoyaltyRewards-MCPServer:8000
```

---

### 3.3 LoyaltyRewards-TestClient (Port 8001)

**Responsibilities:** Human-readable web dashboard for direct testing of the REST API without AI involvement. Useful for debugging and QA.

---

## 4. Agentic Loop — Detailed Flow

```
User message
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  run_agent(conversation: list[dict]) → (reply, updated_conv)│
│                                                            │
│  ┌─────────────────────────────────┐                      │
│  │ 1. list_anthropic_tools()       │                      │
│  │    → MCP SSE → list tools       │                      │
│  │    → convert to Anthropic format│                      │
│  └────────────────┬────────────────┘                      │
│                   │                                        │
│  ┌────────────────▼────────────────┐                      │
│  │ 2. client.messages.create()     │  ◄─── loops up to    │
│  │    model: claude-sonnet-4-6              │    MAX_TOOL_ROUNDS │
│  │    system: SYSTEM_PROMPT        │    (default: 10)     │
│  │    tools: [mcp_tools...]        │                      │
│  │    messages: full_history       │                      │
│  └────────────────┬────────────────┘                      │
│                   │                                        │
│         ┌─────────▼──────────┐                            │
│         │ response analysis  │                            │
│         └──────┬──────┬──────┘                            │
│    stop_reason │      │ tool_use blocks present           │
│    = end_turn  │      │                                   │
│                │  ┌───▼───────────────────────────────┐  │
│                │  │ 3. For each tool_use block:        │  │
│                │  │    call_tool(name, input)          │  │
│                │  │    → MCP SSE → execute tool        │  │
│                │  │    collect tool_result             │  │
│                │  └───────────────────┬───────────────┘  │
│                │                      │                   │
│                │  ┌───────────────────▼───────────────┐  │
│                │  │ 4. Append assistant + tool_result  │  │
│                │  │    messages to history             │  │
│                │  │    → loop back to step 2           │  │
│                │  └───────────────────────────────────┘  │
│                │                                          │
│      ┌─────────▼──────────┐                              │
│      │ 5. Return final    │                              │
│      │    text reply      │                              │
│      └────────────────────┘                              │
└────────────────────────────────────────────────────────────┘
```

---

## 5. MCP Protocol Integration

### Transport: SSE (Server-Sent Events)

```
Claude Client                    MCP Server
     │                                │
     │  GET /mcp/sse                  │
     │ ──────────────────────────►    │
     │  ◄── SSE stream established ── │
     │                                │
     │  initialize()                  │
     │ ──────────────────────────►    │
     │  ◄── capabilities ──────────── │
     │                                │
     │  list_tools()                  │
     │ ──────────────────────────►    │
     │  ◄── [tool1, tool2, ...] ───── │
     │                                │
     │  call_tool("get_rewards_       │
     │   balance", {customer_id})     │
     │ ──────────────────────────►    │
     │  ◄── {points: 1500, ...} ───── │
     │                                │
     │  (connection closed)           │
```

Each `call_tool()` opens a fresh SSE connection. This is stateless and Docker-network-friendly, trading connection overhead for simplicity.

### Tool Schema Conversion

MCP tools are auto-converted to the Anthropic tool format by `mcp_client.list_anthropic_tools()`:

```python
# MCP format (from server)
Tool(name="get_rewards_balance",
     description="...",
     inputSchema={"type": "object", "properties": {"customer_id": ...}})

# Anthropic SDK format (for Claude)
{
  "name": "get_rewards_balance",
  "description": "...",
  "input_schema": {"type": "object", "properties": {"customer_id": ...}}
}
```

---

## 6. API Design

### Chat API

```
POST /api/chat
Content-Type: application/json

{
  "message": "Award 200 points to Alice for her $200 purchase",
  "session_id": "optional-uuid-for-multi-turn"
}

→ 200 OK
{
  "reply": "Done! I've awarded 200 points to Alice...",
  "session_id": "3f7a-...",
  "tool_calls_made": 2
}
```

### Session Management

Sessions are keyed by UUID and stored in-memory as full Anthropic message history lists. Each session preserves the complete conversation context, enabling coherent multi-turn interactions (e.g. "now redeem 2 blocks for her").

**Production note:** Replace the in-memory `SESSIONS` dict with Redis for horizontal scaling and persistence across restarts.

---

## 7. Security Considerations

| Concern | Current approach | Production recommendation |
|---|---|---|
| API key exposure | Env var, never in code | Use Docker secrets or a vault (e.g. AWS Secrets Manager) |
| Session isolation | UUID-keyed dict | Add auth middleware; bind sessions to authenticated users |
| Tool authorisation | All MCP tools available to all users | Add role-based tool filtering in agent.py |
| Rate limiting | None | Add `slowapi` middleware on `/api/chat` |
| Input validation | Pydantic models | Add max message length, profanity filters as needed |
| Prompt injection | System prompt sets boundaries | Monitor tool call patterns; add anomaly detection |

---

## 8. Scalability

### Current (Single-node)

```
All services on one Docker host
SQLite for storage (sufficient to ~10k customers, ~1M transactions)
In-memory session store
```

### Scale-out Path

```
┌─────────────────────────────────────────────────────┐
│  Nginx / Load Balancer                               │
└────────────┬──────────────────┬─────────────────────┘
             ▼                  ▼
    ┌─────────────────┐  ┌─────────────────┐
    │ ClaudeClient #1 │  │ ClaudeClient #2 │
    └────────┬────────┘  └────────┬────────┘
             └──────────┬─────────┘
                        ▼
              ┌──────────────────┐
              │ Redis (sessions) │
              └────────┬─────────┘
                       ▼
             ┌──────────────────────┐
             │ MCPServer (stateless)│
             └────────┬─────────────┘
                      ▼
           ┌──────────────────────────┐
           │ PostgreSQL (replace SQLite│
           │ for multi-node writes)    │
           └──────────────────────────┘
```

---

## 9. Observability

| Signal | Implementation | Recommendation |
|---|---|---|
| Health | `GET /health` on all services | Wire to Prometheus + Grafana |
| Logs | Structured stdout | Ship to Datadog / ELK |
| Traces | None | Add OpenTelemetry → Jaeger |
| Tool metrics | `tool_calls_made` in response | Emit as Prometheus counter |
| LLM costs | None | Track via Anthropic usage API |

---

## 10. Deployment

### Local (Docker Compose)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up --build
```

### Production (Kubernetes sketch)

```yaml
# Each service as a Deployment
# MCPServer: 2 replicas (stateless compute)
# ClaudeClient: 2+ replicas (stateless, Redis for sessions)
# SQLite → PVC or migrate to PostgreSQL
# Secrets: K8s Secret for ANTHROPIC_API_KEY
# Ingress: path-based routing
#   /        → ClaudeClient:8002
#   /test     → TestClient:8001
#   /api      → MCPServer:8000
#   /mcp/sse  → MCPServer:8000
```

---

## 11. Technology Choices

| Component | Technology | Rationale |
|---|---|---|
| LLM | Claude claude-sonnet-4-6 (Anthropic) | Best tool-use reasoning; deterministic, structured JSON outputs |
| MCP transport | SSE | Stateless; works through Docker NAT; official Anthropic-compatible transport |
| MCP library | `mcp` (Python) | Official SDK; handles SSE framing, session init, schema parsing |
| Anthropic SDK | `anthropic` (Python) | Native tool_use support; streaming; async-compatible |
| API framework | FastAPI | Async-first; Pydantic validation; OpenAPI docs out of the box |
| Database | SQLite WAL | Zero ops; sufficient for loyalty workloads; swappable via DB_PATH env |
| Container | Docker + Compose | Reproducible local dev; straight path to K8s |

---

## 12. Development Guide

### Adding a New MCP Tool

1. Add the tool function in `LoyaltyRewards-MCPServer/main.py` using `@mcp.tool()`
2. Add corresponding business logic to `database.py`
3. Optionally add a REST endpoint for the TestClient
4. Restart containers — ClaudeClient auto-discovers tools via `list_tools()`
5. Update the `SYSTEM_PROMPT` in `agent.py` if the tool needs behavioural guidance

### Modifying Claude's Behaviour

Edit `SYSTEM_PROMPT` in `LoyaltyRewards-ClaudeClient/agent.py`:
- Add business rules
- Add guardrails (e.g. "always confirm before redeeming")
- Change response format preferences
- Restrict which tools Claude should prefer

### Running Without Docker

```bash
# Terminal 1 — MCP Server
cd LoyaltyRewards-MCPServer
pip install -r requirements.txt
uvicorn main:app --port 8000

# Terminal 2 — Claude Client
cd LoyaltyRewards-ClaudeClient
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export MCP_SERVER_URL=http://localhost:8000
uvicorn main:app --port 8002
```
