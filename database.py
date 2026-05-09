"""
database.py — SQLite storage for transactions, bills, budgets.
All data stays in a local SQLite file (finance.db).
On Streamlit Cloud, this persists across sessions via st.session_state + file.
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Optional
import pandas as pd

DB_PATH = "finance.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            amount      REAL    NOT NULL,
            type        TEXT    NOT NULL DEFAULT 'DEBIT',   -- DEBIT | CREDIT
            merchant    TEXT    NOT NULL DEFAULT 'Unknown',
            category    TEXT    NOT NULL DEFAULT 'Other',
            bank        TEXT    DEFAULT '',
            account_last4 TEXT  DEFAULT '',
            balance     REAL,
            source      TEXT    DEFAULT 'EMAIL',            -- EMAIL | SMS | MANUAL
            raw_message TEXT    DEFAULT '',
            hash        TEXT    UNIQUE,
            ts          INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
        );

        CREATE TABLE IF NOT EXISTS bills (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            amount          REAL    NOT NULL,
            frequency       TEXT    DEFAULT 'MONTHLY',
            due_day         INTEGER DEFAULT 1,
            category        TEXT    DEFAULT 'Utilities',
            status          TEXT    DEFAULT 'PENDING',      -- PENDING | PAID | OVERDUE
            last_paid_ts    INTEGER,
            next_due_ts     INTEGER,
            auto_detected   INTEGER DEFAULT 0,
            keyword         TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS budgets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT    NOT NULL,
            monthly_limit REAL  NOT NULL,
            month       INTEGER NOT NULL,
            year        INTEGER NOT NULL,
            UNIQUE(category, month, year)
        );

        CREATE INDEX IF NOT EXISTS idx_tx_ts       ON transactions(ts);
        CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);
        CREATE INDEX IF NOT EXISTS idx_tx_type     ON transactions(type);
        CREATE INDEX IF NOT EXISTS idx_tx_hash     ON transactions(hash);
    """)
    conn.commit()
    conn.close()


# ── Transactions ──────────────────────────────────────────────────────────────

def insert_transaction(tx: dict) -> bool:
    """Returns True if inserted, False if duplicate."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO transactions
                (amount, type, merchant, category, bank, account_last4,
                 balance, source, raw_message, hash, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx["amount"], tx.get("type", "DEBIT"), tx.get("merchant", "Unknown"),
            tx.get("category", "Other"), tx.get("bank", ""),
            tx.get("account_last4", ""), tx.get("balance"),
            tx.get("source", "EMAIL"), tx.get("raw", "")[:500],
            tx.get("hash"), tx.get("ts", int(datetime.now().timestamp() * 1000))
        ))
        inserted = conn.total_changes > 0
        conn.commit()
        return inserted
    finally:
        conn.close()


def get_transactions_df(start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> pd.DataFrame:
    conn = get_conn()
    query = "SELECT * FROM transactions WHERE type='DEBIT'"
    params = []
    if start_ts:
        query += " AND ts >= ?"
        params.append(start_ts)
    if end_ts:
        query += " AND ts <= ?"
        params.append(end_ts)
    query += " ORDER BY ts DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def get_all_transactions_df() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY ts DESC", conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def hash_exists(h: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM transactions WHERE hash=?", (h,)).fetchone()
    conn.close()
    return row is not None


def update_transaction_category(tx_id: int, category: str):
    conn = get_conn()
    conn.execute("UPDATE transactions SET category=? WHERE id=?", (category, tx_id))
    conn.commit()
    conn.close()


def delete_transaction(tx_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    conn.commit()
    conn.close()


# ── Bills ─────────────────────────────────────────────────────────────────────

def get_bills_df() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM bills ORDER BY next_due_ts ASC", conn)
    conn.close()
    if not df.empty and "next_due_ts" in df.columns:
        df["due_date"] = pd.to_datetime(df["next_due_ts"], unit="ms", errors="coerce")
    return df


def insert_bill(bill: dict) -> int:
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO bills (name, amount, frequency, due_day, category,
                           status, next_due_ts, auto_detected, keyword)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        bill["name"], bill["amount"], bill.get("frequency", "MONTHLY"),
        bill.get("due_day", 1), bill.get("category", "Utilities"),
        "PENDING", bill.get("next_due_ts", 0),
        1 if bill.get("auto_detected") else 0, bill.get("keyword", "")
    ))
    conn.commit()
    bill_id = cursor.lastrowid
    conn.close()
    return bill_id


def mark_bill_paid(bill_id: int):
    conn = get_conn()
    conn.execute("""
        UPDATE bills SET status='PAID', last_paid_ts=?
        WHERE id=?
    """, (int(datetime.now().timestamp() * 1000), bill_id))
    conn.commit()
    conn.close()


def update_bill_status(bill_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE bills SET status=? WHERE id=?", (status, bill_id))
    conn.commit()
    conn.close()


def delete_bill(bill_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM bills WHERE id=?", (bill_id,))
    conn.commit()
    conn.close()


def find_matching_bill(amount: float, bank_hint: str = "") -> Optional[dict]:
    """Find a PENDING bill whose amount is within 5% of the payment."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM bills WHERE status='PENDING'").fetchall()
    conn.close()
    for row in rows:
        diff = abs(row["amount"] - amount)
        if row["amount"] > 0 and (diff / row["amount"]) <= 0.05:
            if not bank_hint or bank_hint.lower() in row["name"].lower():
                return dict(row)
    return None


def bill_duplicate(name: str, amount: float) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM bills WHERE name=? AND ABS(amount-?)<=? AND status='PENDING'",
        (name, amount, amount * 0.02)
    ).fetchone()
    conn.close()
    return row is not None


# ── Budgets ───────────────────────────────────────────────────────────────────

def get_budgets_df(month: int, year: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM budgets WHERE month=? AND year=?", conn, params=(month, year)
    )
    conn.close()
    return df


def set_budget(category: str, limit: float, month: int, year: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO budgets (category, monthly_limit, month, year)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category, month, year)
        DO UPDATE SET monthly_limit=excluded.monthly_limit
    """, (category, limit, month, year))
    conn.commit()
    conn.close()


# ── Summary queries ───────────────────────────────────────────────────────────

def get_category_spend(start_ts: int, end_ts: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT category, SUM(amount) as total
        FROM transactions
        WHERE type='DEBIT' AND ts BETWEEN ? AND ?
        GROUP BY category
        ORDER BY total DESC
    """, conn, params=(start_ts, end_ts))
    conn.close()
    return df


def get_daily_spend(start_ts: int, end_ts: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT date(ts/1000, 'unixepoch', 'localtime') as day,
               SUM(amount) as total
        FROM transactions
        WHERE type='DEBIT' AND ts BETWEEN ? AND ?
        GROUP BY day ORDER BY day
    """, conn, params=(start_ts, end_ts))
    conn.close()
    return df


def get_weekly_spend_history() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT strftime('%Y-W%W', ts/1000, 'unixepoch', 'localtime') as week,
               SUM(amount) as total
        FROM transactions
        WHERE type='DEBIT'
        GROUP BY week ORDER BY week
    """, conn)
    conn.close()
    return df


def get_monthly_spend_history() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT strftime('%Y-%m', ts/1000, 'unixepoch', 'localtime') as month,
               SUM(amount) as total
        FROM transactions
        WHERE type='DEBIT'
        GROUP BY month ORDER BY month
    """, conn)
    conn.close()
    return df
