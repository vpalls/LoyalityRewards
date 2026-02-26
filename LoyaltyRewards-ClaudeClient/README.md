# 🏆 Loyalty Rewards — AI-Powered Platform

A production-grade **Model Context Protocol (MCP)** loyalty rewards engine with three services: an MCP/REST server, a testing dashboard, and a **Claude AI chat interface** — fully containerised with Docker.

---

## Project Structure

```
📁 LoyaltyRewards-MCPServer/          ← Port 8000
│   ├── main.py                        # FastMCP tools + FastAPI REST API
│   ├── database.py                    # SQLite business logic & point ledger
│   ├── requirements.txt
│   └── Dockerfile

📁 LoyaltyRewards-TestClient/         ← Port 8001
│   ├── main.py                        # FastAPI testing dashboard
│   ├── requirements.txt
│   ├── Dockerfile
│   └── templates/
│       ├── index.html                 # Customer roster + quick actions
│       └── customer.html             # Customer detail + transaction ledger

📁 LoyaltyRewards-ClaudeClient/       ← Port 8002  ✨ NEW
│   ├── main.py                        # FastAPI app: chat API + web UI
│   ├── agent.py                       # Agentic loop (Claude + MCP tool-use)
│   ├── mcp_client.py                  # MCP SSE client helper
│   ├── requirements.txt
│   ├── Dockerfile
│   └── templates/
│       └── chat.html                  # Dark-themed AI chat interface

📄 docker-compose.yml                 # Orchestrates all three containers
📄 README.md
📄 SYSTEM_DESIGN.md
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Docker Network (loyalty-net)                        │
│                                                                              │
│  ┌───────────────────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │  LoyaltyRewards-MCPServer     │  │ TestClient       │  │ ClaudeClient │ │
│  │  Port 8000                    │  │ Port 8001        │  │ Port 8002    │ │
│  │                               │  │                  │  │              │ │
│  │  ┌──────────┐  /mcp/sse  ◄───┼──┼──────────────────┼──┤  agent.py   │ │
│  │  │ FastMCP  │  (SSE)         │  │  Web Dashboard   │  │  (agentic    │ │
│  │  │ AI Tools │                │  │  REST calls  ↕   │  │   loop)      │ │
│  │  └──────────┘                │  └─────────────────┘  │              │ │
│  │  ┌──────────┐  /api/*   ◄───┼──────────────────────  │  Claude API  │ │
│  │  │ FastAPI  │  (HTTP)        │                        │  ↕ (cloud)   │ │
│  │  │ REST API │                │                        └──────────────┘ │
│  │  └──────────┘                │                                          │
│  │  ┌──────────┐                │                                          │
│  │  │ SQLite   │ /data/         │                                          │
│  │  └──────────┘                │                                          │
│  └───────────────────────────────┘                                         │
└────────────────────────────────────────────────────────────────────────────┘
                                          ▲
                                          │ ANTHROPIC_API_KEY (env)
                                          │ Claude claude-sonnet-4-6
```

### Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| MCP transport | SSE over HTTP | Works across Docker containers; Claude-compatible |
| Database | SQLite + WAL mode | Zero-dependency, persistent volume, sufficient for loyalty workloads |
| REST + MCP dual exposure | Yes | REST for the testing client; MCP tools for AI agents |
| Point ledger | Append-only | Auditable — historical records are never mutated |
| Tier upgrade | Automatic | Based on cumulative lifetime points earned, not current balance |
| LLM model | Claude claude-sonnet-4-6 | Best-in-class tool-use reasoning; cost-efficient for transactional tasks |
| Agentic loop | Custom (agent.py) | Full control over tool-round limits, error handling, session management |
| Session state | In-memory dict | Sufficient for demo; swap for Redis in production |

---

## Business Rules

| Rule | Value |
|---|---|
| Points per $1 spent | **1 point** |
| Minimum to redeem | **1,000 points** |
| Cash per 1,000-point block | **$10.00 store cash** |
| Tiers | 🥉 Bronze (0+) · 🥈 Silver (2,000+) · 🥇 Gold (5,000+) · 🏆 Platinum (10,000+) |

---

## Quick Start

```bash
# 1. Place all three project folders and the files below in the same directory:
#    LoyaltyRewards-MCPServer/
#    LoyaltyRewards-TestClient/
#    LoyaltyRewards-ClaudeClient/
#    docker-compose.yml

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Build and run
docker compose up --build
```

| Interface | URL |
|---|---|
| 🤖 Claude AI Chat | http://localhost:8002 |
| 🧪 Testing Dashboard | http://localhost:8001 |
| 📖 REST API Swagger | http://localhost:8000/docs |
| 🔌 MCP SSE Endpoint | http://localhost:8000/mcp/sse |

---

## Claude AI Chat — How It Works

```
User types a message
        │
        ▼
  POST /api/chat
        │
        ▼
  agent.py: run_agent()
   ┌─────────────────────────────────────────────────────┐
   │  1. Fetch available tools from MCP server           │
   │  2. Call Claude claude-sonnet-4-6 with history + tools        │
   │  3. If Claude requests tool_use:                    │
   │       a. Execute each tool via MCP SSE              │
   │       b. Append tool_result to message history      │
   │       c. Loop back to step 2                        │
   │  4. Return final text response                      │
   └─────────────────────────────────────────────────────┘
        │
        ▼
  JSON response → rendered in chat UI
```

### Example Prompts

```
"Register Alice Smith with email alice@company.com"
"Award 500 points to Alice for her purchase of $500"
"What's Alice's current rewards balance and tier?"
"How much store cash can Alice redeem right now?"
"Show me Alice's full transaction history"
"Redeem 2 blocks of rewards for Alice"
"List all customers and their point balances"
```

---

## REST API Reference

### Customers

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/customers` | Register a new customer |
| `GET` | `/api/customers` | List all customers |
| `GET` | `/api/customers/{id}` | Get customer details |

### Rewards

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/rewards/{id}/balance` | Available points + redeemable cash |
| `POST` | `/api/rewards/{id}/earn` | Award points for a purchase (1 pt / $1) |
| `GET` | `/api/rewards/{id}/redeemable` | Redeemable store cash value |
| `POST` | `/api/rewards/{id}/redeem` | Redeem N × 1,000 pts for N × $10 store cash |
| `GET` | `/api/rewards/{id}/history` | Full earn / redeem transaction ledger |

### Claude Chat API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Full agentic response (JSON) |
| `POST` | `/api/chat/stream` | Server-Sent Events streaming |
| `GET` | `/api/tools` | List tools discovered from MCP server |
| `DELETE` | `/api/sessions/{id}` | Clear a conversation session |
| `GET` | `/health` | Liveness + MCP server reachability |

---

## MCP Tools (for Claude / AI Agents)

Connect via: `http://localhost:8000/mcp/sse`

| Tool | Parameters | Description |
|---|---|---|
| `create_customer` | `name`, `email` | Register a new customer |
| `get_rewards_balance` | `customer_id` | Current points balance + redeemable cash |
| `post_rewards` | `customer_id`, `amount_spent`, `description?` | Award purchase points |
| `get_redeemable_cash` | `customer_id` | Redeemable store cash value |
| `redeem_rewards` | `customer_id`, `blocks?` | Redeem reward blocks (1,000 pts → $10) |
| `list_customers` | — | All registered customers |
| `get_transaction_history` | `customer_id`, `limit?` | Earn / redeem transaction ledger |

---

## Environment Variables

### LoyaltyRewards-MCPServer

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/loyalty.db` | SQLite database file path |

### LoyaltyRewards-TestClient

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_URL` | `http://mcp-server:8000` | Base URL of the MCP server |

### LoyaltyRewards-ClaudeClient ✨

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | Your Anthropic API key |
| `MCP_SERVER_URL` | Default: `http://mcp-server:8000` | MCP server base URL |

---

## Connecting Claude.ai Directly (Optional)

You can also connect Claude.ai's native MCP integration directly to your server:

1. In Claude.ai → Settings → Integrations → Add MCP Server
2. URL: `http://localhost:8000/mcp/sse`
3. Claude will automatically discover and use all loyalty rewards tools

This bypasses the ClaudeClient entirely — useful for ad-hoc exploration.
