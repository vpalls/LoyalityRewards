import sqlite3
import os
import uuid
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "/data/loyalty.db")


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            tier        TEXT NOT NULL DEFAULT 'Bronze',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS point_ledger (
            id               TEXT PRIMARY KEY,
            customer_id      TEXT NOT NULL,
            points           INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,   -- 'earn' | 'redeem'
            amount_spent     REAL,            -- only for earn
            cash_value       REAL,            -- only for redeem
            description      TEXT,
            created_at       TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_customer ON point_ledger(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ledger_type     ON point_ledger(transaction_type);
    """)
    conn.commit()
    conn.close()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ── Customer helpers ──────────────────────────────────────────────────────────

def create_customer(name: str, email: str) -> dict:
    conn = get_db()
    try:
        cid = new_id()
        conn.execute(
            "INSERT INTO customers (id, name, email, tier, created_at) VALUES (?,?,?,?,?)",
            (cid, name, email, "Bronze", now_iso()),
        )
        conn.commit()
        return {"id": cid, "name": name, "email": email, "tier": "Bronze"}
    finally:
        conn.close()


def get_customer(customer_id: str) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_customers() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Points helpers ────────────────────────────────────────────────────────────

POINTS_PER_DOLLAR = 1          # 1 point per $1
POINTS_PER_REWARD_BLOCK = 1000 # 1000 points = $10
CASH_PER_REWARD_BLOCK = 10.0


def _tier(total_earned: int) -> str:
    if total_earned >= 10_000:
        return "Platinum"
    if total_earned >= 5_000:
        return "Gold"
    if total_earned >= 2_000:
        return "Silver"
    return "Bronze"


def _balance(conn: sqlite3.Connection, customer_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(points),0) AS bal FROM point_ledger WHERE customer_id=?",
        (customer_id,),
    ).fetchone()
    return int(row["bal"])


def _total_earned(conn: sqlite3.Connection, customer_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(points),0) AS tot FROM point_ledger "
        "WHERE customer_id=? AND transaction_type='earn'",
        (customer_id,),
    ).fetchone()
    return int(row["tot"])


def earn_points(customer_id: str, amount_spent: float, description: str = "") -> dict:
    """Award points for a purchase (1 point per $1)."""
    conn = get_db()
    try:
        customer = conn.execute("SELECT id FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found.")

        points = int(amount_spent * POINTS_PER_DOLLAR)
        if points <= 0:
            raise ValueError("Amount must be at least $1.")

        lid = new_id()
        conn.execute(
            "INSERT INTO point_ledger (id,customer_id,points,transaction_type,amount_spent,description,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (lid, customer_id, points, "earn", amount_spent, description or f"Purchase ${amount_spent:.2f}", now_iso()),
        )

        balance = _balance(conn, customer_id) + points  # after insert
        # Fix: re-read after commit
        conn.commit()
        balance = _balance(conn, customer_id)
        total = _total_earned(conn, customer_id)
        tier = _tier(total)
        conn.execute("UPDATE customers SET tier=? WHERE id=?", (tier, customer_id))
        conn.commit()

        return {
            "points_earned": points,
            "amount_spent": amount_spent,
            "new_balance": balance,
            "total_earned": total,
            "tier": tier,
        }
    finally:
        conn.close()


def get_balance(customer_id: str) -> dict:
    """Get current points balance and redeemable cash."""
    conn = get_db()
    try:
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found.")

        balance = _balance(conn, customer_id)
        total_earned = _total_earned(conn, customer_id)
        redeemable_blocks = balance // POINTS_PER_REWARD_BLOCK
        redeemable_cash = redeemable_blocks * CASH_PER_REWARD_BLOCK
        points_to_next = POINTS_PER_REWARD_BLOCK - (balance % POINTS_PER_REWARD_BLOCK) if balance % POINTS_PER_REWARD_BLOCK != 0 else 0

        return {
            "customer_id": customer_id,
            "customer_name": customer["name"],
            "email": customer["email"],
            "tier": customer["tier"],
            "available_points": balance,
            "total_points_earned": total_earned,
            "redeemable_cash": redeemable_cash,
            "redeemable_blocks": redeemable_blocks,
            "points_per_block": POINTS_PER_REWARD_BLOCK,
            "cash_per_block": CASH_PER_REWARD_BLOCK,
            "points_to_next_reward": points_to_next if balance < POINTS_PER_REWARD_BLOCK else 0,
            "can_redeem": balance >= POINTS_PER_REWARD_BLOCK,
        }
    finally:
        conn.close()


def redeem_points(customer_id: str, blocks: int = 1) -> dict:
    """Redeem N blocks of 1000 points for $10 store cash each."""
    conn = get_db()
    try:
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found.")

        balance = _balance(conn, customer_id)
        points_needed = blocks * POINTS_PER_REWARD_BLOCK
        cash_value = blocks * CASH_PER_REWARD_BLOCK

        if balance < POINTS_PER_REWARD_BLOCK:
            raise ValueError(
                f"Insufficient points. You have {balance} points. "
                f"Minimum {POINTS_PER_REWARD_BLOCK} required to redeem."
            )
        if balance < points_needed:
            max_blocks = balance // POINTS_PER_REWARD_BLOCK
            raise ValueError(
                f"Not enough points for {blocks} block(s). "
                f"You can redeem up to {max_blocks} block(s) ({max_blocks * POINTS_PER_REWARD_BLOCK} points)."
            )

        lid = new_id()
        conn.execute(
            "INSERT INTO point_ledger (id,customer_id,points,transaction_type,cash_value,description,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (lid, customer_id, -points_needed, "redeem", cash_value,
             f"Redeemed {points_needed} points for ${cash_value:.2f} store cash", now_iso()),
        )
        conn.commit()
        new_balance = _balance(conn, customer_id)

        return {
            "points_redeemed": points_needed,
            "cash_awarded": cash_value,
            "remaining_points": new_balance,
            "transaction_id": lid,
        }
    finally:
        conn.close()


def get_transaction_history(customer_id: str, limit: int = 20) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM point_ledger WHERE customer_id=? ORDER BY created_at DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
