"""
Loyalty Rewards MCP Server
==========================
Exposes both:
  • MCP tools (SSE at /mcp/sse)  ← for Claude / AI agents
  • REST API   (at /api/*)       ← for the testing client
"""

from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount, Route

import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("loyalty-mcp")

# ─────────────────────────────────────────────────────────────────────────────
# FastMCP instance
# ─────────────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="Loyalty Rewards Server",
    instructions=(
        "Manage customer loyalty points. "
        "1 point per $1 spent. "
        "1 000 points redeemable for $10 store cash."
    ),
)


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool(description="Create a new loyalty customer account.")
def create_customer(name: str, email: str) -> dict:
    """Register a new customer."""
    try:
        return db.create_customer(name, email)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(description="Get the current rewards balance for a customer.")
def get_rewards_balance(customer_id: str) -> dict:
    """
    Returns available points, redeemable cash, tier, and whether
    the customer can currently redeem rewards.
    """
    try:
        return db.get_balance(customer_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(description="Post purchase points for a customer (1 point per $1 spent).")
def post_rewards(customer_id: str, amount_spent: float, description: str = "") -> dict:
    """Award loyalty points based on purchase amount."""
    try:
        return db.earn_points(customer_id, amount_spent, description)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(description="Get redeemable store cash for a customer.")
def get_redeemable_cash(customer_id: str) -> dict:
    """
    Returns how much store cash the customer can redeem right now.
    Minimum 1 000 points required per redemption block.
    """
    try:
        bal = db.get_balance(customer_id)
        return {
            "customer_id": customer_id,
            "available_points": bal["available_points"],
            "redeemable_cash": bal["redeemable_cash"],
            "redeemable_blocks": bal["redeemable_blocks"],
            "can_redeem": bal["can_redeem"],
            "minimum_points_required": db.POINTS_PER_REWARD_BLOCK,
            "message": (
                f"${bal['redeemable_cash']:.2f} store cash available"
                if bal["can_redeem"]
                else f"Need {bal['points_to_next_reward']} more points to unlock first reward"
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(description="Redeem loyalty points for store cash.")
def redeem_rewards(customer_id: str, blocks: int = 1) -> dict:
    """
    Redeem N blocks of 1 000 points for $10 store cash each.
    Fails if customer has fewer than 1 000 points.
    """
    try:
        return db.redeem_points(customer_id, blocks)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(description="List all registered customers.")
def list_customers() -> list[dict]:
    """Return all customers in the loyalty programme."""
    return db.list_customers()


@mcp.tool(description="Get transaction history for a customer.")
def get_transaction_history(customer_id: str, limit: int = 20) -> list[dict]:
    """Return recent earn/redeem transactions for a customer."""
    try:
        return db.get_transaction_history(customer_id, limit)
    except Exception as exc:
        return [{"error": str(exc)}]


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app (REST layer)
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Database initialised.")
    yield

app = FastAPI(
    title="Loyalty Rewards Service",
    version="1.0.0",
    description="MCP-powered customer loyalty rewards engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up MCP SSE transport and mount at /mcp
# Client connects to GET /mcp/sse; messages are POSTed to /mcp/messages/
_sse_transport = SseServerTransport("/mcp/messages/")


async def _handle_sse(request):
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0],
            streams[1],
            mcp._mcp_server.create_initialization_options(),
        )


app.mount(
    "/mcp",
    Starlette(
        routes=[
            Route("/sse", endpoint=_handle_sse),
            Mount("/messages/", app=_sse_transport.handle_post_message),
        ]
    ),
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, example="Jane Doe")
    email: str = Field(..., example="jane@example.com")


class EarnRequest(BaseModel):
    amount_spent: float = Field(..., gt=0, example=49.99)
    description: str = Field("", example="Online order #1234")


class RedeemRequest(BaseModel):
    blocks: int = Field(1, ge=1, description="Number of 1000-point blocks to redeem")


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "loyalty-rewards-mcp"}


@app.post("/api/customers", status_code=201, tags=["Customers"])
def api_create_customer(body: CustomerCreate):
    """Register a new loyalty customer."""
    try:
        return db.create_customer(body.name, body.email)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/customers", tags=["Customers"])
def api_list_customers():
    """List all loyalty customers."""
    return db.list_customers()


@app.get("/api/customers/{customer_id}", tags=["Customers"])
def api_get_customer(customer_id: str):
    customer = db.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return customer


@app.get("/api/rewards/{customer_id}/balance", tags=["Rewards"])
def api_get_rewards_balance(customer_id: str):
    """GetRewardsBalance — returns available points and redeemable cash."""
    try:
        return db.get_balance(customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/rewards/{customer_id}/earn", tags=["Rewards"])
def api_post_rewards(customer_id: str, body: EarnRequest):
    """PostRewards — award points for a purchase (1 pt per $1 spent)."""
    try:
        return db.earn_points(customer_id, body.amount_spent, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/rewards/{customer_id}/redeemable", tags=["Rewards"])
def api_get_redeemable_cash(customer_id: str):
    """GetRedeemableCash — returns available store-cash value."""
    try:
        bal = db.get_balance(customer_id)
        return {
            "customer_id": customer_id,
            "available_points": bal["available_points"],
            "redeemable_cash": bal["redeemable_cash"],
            "redeemable_blocks": bal["redeemable_blocks"],
            "can_redeem": bal["can_redeem"],
            "minimum_points_required": db.POINTS_PER_REWARD_BLOCK,
            "message": (
                f"${bal['redeemable_cash']:.2f} store cash available"
                if bal["can_redeem"]
                else f"Need {bal['points_to_next_reward']} more points to unlock first reward"
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/rewards/{customer_id}/redeem", tags=["Rewards"])
def api_redeem_rewards(customer_id: str, body: RedeemRequest):
    """Redeem N × 1000 points for N × $10 store cash."""
    try:
        return db.redeem_points(customer_id, body.blocks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/rewards/{customer_id}/history", tags=["Rewards"])
def api_transaction_history(customer_id: str, limit: int = 20):
    """Full earn/redeem transaction ledger for a customer."""
    try:
        return db.get_transaction_history(customer_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
