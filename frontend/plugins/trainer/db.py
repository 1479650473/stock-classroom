# -*- coding: utf-8 -*-
"""Training records — SQLite persistence."""

import sqlite3, os


def _ensure_tables(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trainer_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            total_bars INTEGER,
            initial_balance REAL,
            final_balance REAL,
            final_equity REAL,
            total_trades INTEGER,
            win_rate REAL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS trainer_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            side TEXT NOT NULL,
            qty INTEGER,
            entry_price REAL,
            entry_idx INTEGER,
            entry_date TEXT,
            exit_price REAL,
            exit_idx INTEGER,
            exit_date TEXT,
            stop_loss REAL,
            take_profit REAL,
            pnl REAL,
            commission REAL,
            status TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (session_id) REFERENCES trainer_sessions(id)
        );
    """)
    conn.commit()
    conn.close()


def _get_db_path():
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "data", "trainer.db")
    proj = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(proj, "data", "trainer.db")


DB_PATH = _get_db_path()


def create_session(stock_code, stock_name, total_bars, initial_balance, start_date, end_date):
    _ensure_tables(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        """INSERT INTO trainer_sessions (stock_code, stock_name, total_bars, initial_balance, start_date, end_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (stock_code, stock_name, total_bars, initial_balance, start_date, end_date)
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def save_trade(session_id, order):
    _ensure_tables(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO trainer_trades
           (session_id, side, qty, entry_price, entry_idx, entry_date,
            exit_price, exit_idx, exit_date, stop_loss, take_profit, pnl, commission, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            order.side,
            int(order.qty),
            order.entry_price,
            order.entry_idx,
            order.entry_date or '',
            order.exit_price or 0,
            order.exit_idx or 0,
            order.exit_date or '',
            order.stop_loss or 0,
            order.take_profit or 0,
            order.pnl,
            order.commission,
            order.status,
        )
    )
    conn.commit()
    conn.close()


def finish_session(session_id, engine):
    _ensure_tables(DB_PATH)
    snap = engine.snapshot()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """UPDATE trainer_sessions SET final_balance=?, final_equity=?, total_trades=?, win_rate=?
           WHERE id=?""",
        (engine.balance, snap['total_equity'], len(engine.closed_orders), snap['win_rate'], session_id)
    )
    conn.commit()
    conn.close()


def list_sessions(limit=20):
    _ensure_tables(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trainer_sessions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
