# -*- coding: utf-8 -*-
"""SQLite schema and connection management for sim_trade.db."""

import os, sys, sqlite3

if getattr(sys, 'frozen', False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_db_path():
    data_dir = os.environ.get("SC_DATA_DIR") or os.path.join(PROJECT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "sim_trade.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    initial_capital REAL DEFAULT 100000,
    balance REAL DEFAULT 100000,
    frozen REAL DEFAULT 0,
    total_profit REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    price REAL DEFAULT 0,
    qty INTEGER NOT NULL,
    filled_qty INTEGER DEFAULT 0,
    filled_price REAL,
    status TEXT DEFAULT 'pending',
    commission REAL DEFAULT 0,
    stamp_tax REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    qty INTEGER NOT NULL,
    frozen_qty INTEGER DEFAULT 0,
    cost_price REAL NOT NULL,
    current_price REAL DEFAULT 0,
    market_value REAL DEFAULT 0,
    float_pnl REAL DEFAULT 0,
    last_buy_date TEXT DEFAULT '',
    UNIQUE(account_id, code)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    commission REAL DEFAULT 0,
    stamp_tax REAL DEFAULT 0,
    traded_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS account_nav (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    nav REAL NOT NULL,
    total_assets REAL NOT NULL,
    balance REAL NOT NULL,
    market_value REAL NOT NULL,
    UNIQUE(account_id, date)
);
"""


def ensure_tables(db_path=None):
    if db_path is None:
        db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
