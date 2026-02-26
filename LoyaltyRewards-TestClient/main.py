"""
Loyalty Rewards — FastAPI Testing Client
========================================
A web-based dashboard that exercises every REST endpoint on the
MCP Loyalty Rewards Server. Styled with Bootstrap 5.
"""

from __future__ import annotations
import os
import logging

import httpx
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("loyalty-client")

MCP_BASE = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000")

app = FastAPI(title="Loyalty Rewards Testing Client", version="1.0.0")
templates = Jinja2Templates(directory="templates")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client() -> httpx.Client:
    return httpx.Client(base_url=MCP_BASE, timeout=10)


def _safe_get(path: str) -> dict | list:
    try:
        with _client() as c:
            r = c.get(path)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": e.response.text}
    except Exception as e:
        return {"error": str(e)}


def _safe_post(path: str, payload: dict) -> dict:
    try:
        with _client() as c:
            r = c.post(path, json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": e.response.text}
    except Exception as e:
        return {"error": str(e)}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    customers = _safe_get("/api/customers")
    health    = _safe_get("/health")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "customers": customers if isinstance(customers, list) else [],
        "mcp_url": MCP_BASE,
        "health": health,
    })


@app.post("/customers/create")
async def create_customer(
    request: Request,
    name: str  = Form(...),
    email: str = Form(...),
):
    result = _safe_post("/api/customers", {"name": name, "email": email})
    return RedirectResponse(url=f"/?msg={result}", status_code=303)


@app.get("/customers/{customer_id}", response_class=HTMLResponse)
async def customer_detail(request: Request, customer_id: str):
    balance  = _safe_get(f"/api/rewards/{customer_id}/balance")
    history  = _safe_get(f"/api/rewards/{customer_id}/history")
    redeem   = _safe_get(f"/api/rewards/{customer_id}/redeemable")
    customer = _safe_get(f"/api/customers/{customer_id}")
    return templates.TemplateResponse("customer.html", {
        "request": request,
        "customer": customer,
        "balance": balance,
        "history": history if isinstance(history, list) else [],
        "redeem": redeem,
    })


@app.post("/rewards/earn")
async def earn_points(
    request: Request,
    customer_id:  str   = Form(...),
    amount_spent: float = Form(...),
    description:  str   = Form(""),
):
    _safe_post(f"/api/rewards/{customer_id}/earn", {
        "amount_spent": amount_spent,
        "description": description,
    })
    return RedirectResponse(url=f"/customers/{customer_id}", status_code=303)


@app.post("/rewards/redeem")
async def redeem_points(
    request: Request,
    customer_id: str = Form(...),
    blocks: int      = Form(1),
):
    _safe_post(f"/api/rewards/{customer_id}/redeem", {"blocks": blocks})
    return RedirectResponse(url=f"/customers/{customer_id}", status_code=303)


# ── JSON API passthrough (for JS fetch calls) ─────────────────────────────────

@app.get("/api/proxy/customers")
async def proxy_customers():
    return _safe_get("/api/customers")


@app.get("/api/proxy/balance/{customer_id}")
async def proxy_balance(customer_id: str):
    return _safe_get(f"/api/rewards/{customer_id}/balance")


@app.get("/api/proxy/redeemable/{customer_id}")
async def proxy_redeemable(customer_id: str):
    return _safe_get(f"/api/rewards/{customer_id}/redeemable")


@app.get("/health")
def health():
    mcp_health = _safe_get("/health")
    return {"status": "ok", "mcp_server": mcp_health}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
