# 🏆 Loyalty Rewards MCP Server

A production-grade **Model Context Protocol (MCP)** loyalty rewards engine with a FastAPI testing dashboard, fully containerised with Docker.

---

## Project Structure

```
📁 LoyaltyRewards-MCPServer/
│   ├── main.py              # FastMCP tools + FastAPI REST API
│   ├── database.py          # SQLite business logic & point ledger
│   ├── requirements.txt
│   └── Dockerfile
│
📁 LoyaltyRewards-TestClient/
│   ├── main.py              # FastAPI testing dashboard
│   ├── requirements.txt
│   ├── Dockerfile
│   └── templates/
│       ├── index.html       # Customer roster + quick actions
│       └── customer.html    # Customer detail + transaction ledger
│
📄 docker-compose.yml        # Orchestrates both containers
📄 README.md
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Docker Network (loyalty-net)                   │
│                                                                   │
│  ┌──────────────────────────────────┐   ┌──────────────────────┐ │
│  │   LoyaltyRewards-MCPServer       │   │ LoyaltyRewards-      │ │
│  │   Port 8000                      │   │ TestClient           │ │
│  │                                  │   │ Port 8001            │ │
│  │  ┌────────────┐                  │   │                      │ │
│  │  │  FastMCP   │ /mcp/sse         │   │  Web Dashboard       │ │
│  │  │  (AI Tools)│ ← Claude / Agent │   │  ↕  REST calls       │ │
│  │  └────────────┘                  │   │                      │ │
│  │  ┌────────────┐                  │   └──────────────────────┘ │
│  │  │  FastAPI   │ /api/*           │                            │
│  │  │  REST API  │ ← HTTP           │                            │
│  │  └────────────┘                  │                            │
│  │  ┌────────────┐                  │                            │
│  │  │  SQLite DB │ /data/loyalty.db │                            │
│  │  └────────────┘                  │                            │
│  └──────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────┘
```

### Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| MCP transport | SSE over HTTP | Works across Docker containers; Claude-compatible |
| Database | SQLite + WAL mode | Zero-dependency, persistent volume, sufficient for loyalty workloads |
| REST + MCP dual exposure | Yes | REST for the testing client; MCP tools for AI agents |
| Point ledger | Append-only | Auditable — historical records are never mutated |
| Tier upgrade | Automatic | Based on cumulative lifetime points earned, not current balance |

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
# 1. Place both folders and docker-compose.yml in the same directory
# 2. Run:
docker compose up --build

# Testing Dashboard → http://localhost:8001
# REST API Swagger  → http://localhost:8000/docs
# MCP SSE Endpoint  → http://localhost:8000/mcp/sse
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
| `GET` | `/api/rewards/{id}/balance` | **GetRewardsBalance** — available points + redeemable cash |
| `POST` | `/api/rewards/{id}/earn` | **PostRewards** — award points for a purchase (1 pt / $1) |
| `GET` | `/api/rewards/{id}/redeemable` | **GetRedeemableCash** — redeemable store cash value |
| `POST` | `/api/rewards/{id}/redeem` | Redeem N × 1,000 pts for N × $10 store cash |
| `GET` | `/api/rewards/{id}/history` | Full earn / redeem transaction ledger |

### Example curl Flows

```bash
BASE=http://localhost:8000

# 1. Register a customer
curl -X POST $BASE/api/customers \
  -H "Content-Type: application/json" \
  -d '{"name":"Jane Doe","email":"jane@example.com"}'
# → {"id":"<uuid>","name":"Jane Doe","email":"jane@example.com","tier":"Bronze"}

# 2. Award points ($150 purchase = 150 pts)
curl -X POST $BASE/api/rewards/<uuid>/earn \
  -H "Content-Type: application/json" \
  -d '{"amount_spent":150,"description":"Order #1001"}'
# → {"points_earned":150,"new_balance":150,...}

# 3. Get rewards balance
curl $BASE/api/rewards/<uuid>/balance

# 4. Get redeemable cash
curl $BASE/api/rewards/<uuid>/redeemable

# 5. Redeem rewards (requires ≥ 1,000 pts)
curl -X POST $BASE/api/rewards/<uuid>/redeem \
  -H "Content-Type: application/json" \
  -d '{"blocks":1}'
# → {"points_redeemed":1000,"cash_awarded":10.0,"remaining_points":...}
```

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
