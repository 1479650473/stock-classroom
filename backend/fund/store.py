# -*- coding: utf-8 -*-
"""data/fund_arb.db 的表结构与读写。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Dict, Iterable, List, Optional

from ..api.paths import FUND_ARB_DB

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS lof_list (
  code TEXT PRIMARY KEY,
  name TEXT,
  exchange TEXT,            -- sz | sh
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS lof_daily (
  code TEXT, date TEXT,     -- date: YYYY-MM-DD（未复权原始价）
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL, -- volume: 份；amount: 元
  PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_lof_daily_date ON lof_daily(date);
CREATE TABLE IF NOT EXISTS fund_nav (
  code TEXT, nav_date TEXT, -- nav_date: YYYY-MM-DD
  nav REAL, growth REAL,    -- 单位净值 / 日增长率(%)
  PRIMARY KEY (code, nav_date)
);
CREATE TABLE IF NOT EXISTS fund_fee (
  code TEXT PRIMARY KEY,
  buy_tiers TEXT,           -- JSON: [{"amount": "小于100万", "rate": "1.50%"}, ...]（申购费分档）
  redeem_tiers TEXT,        -- JSON: [{"term": "小于7天", "rate": "1.50%"}, ...]（赎回费分档）
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fund_purchase (
  code TEXT PRIMARY KEY,
  name TEXT, ftype TEXT,
  nav REAL, nav_date TEXT,
  purchase_status TEXT, redeem_status TEXT, next_open TEXT,
  min_amount REAL, daily_limit REAL, fee_rate REAL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS arb_meta (
  key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(FUND_ARB_DB), exist_ok=True)
        c = sqlite3.connect(FUND_ARB_DB, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _local.conn = c
    return c


# ---------------- 写入 ----------------

def upsert_list(rows: Iterable[dict]) -> int:
    c = conn()
    c.executemany(
        "INSERT INTO lof_list(code,name,exchange,updated_at) VALUES(?,?,?,datetime('now','localtime')) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name, exchange=excluded.exchange, updated_at=excluded.updated_at",
        [(r["code"], r.get("name"), r.get("exchange")) for r in rows])
    c.commit()
    return len(list(rows)) if not isinstance(rows, list) else len(rows)


def upsert_daily(rows: Iterable[dict]) -> int:
    """rows: {code,date,open,high,low,close,volume,amount}"""
    c = conn()
    n = 0
    batch = []
    for r in rows:
        batch.append((r["code"], r["date"], r.get("open"), r.get("high"), r.get("low"),
                      r.get("close"), r.get("volume"), r.get("amount")))
        if len(batch) >= 2000:
            c.executemany("INSERT OR REPLACE INTO lof_daily(code,date,open,high,low,close,volume,amount) "
                          "VALUES(?,?,?,?,?,?,?,?)", batch)
            n += len(batch)
            batch = []
    if batch:
        c.executemany("INSERT OR REPLACE INTO lof_daily(code,date,open,high,low,close,volume,amount) "
                      "VALUES(?,?,?,?,?,?,?,?)", batch)
        n += len(batch)
    c.commit()
    return n


def upsert_nav(rows: Iterable[dict]) -> int:
    c = conn()
    batch = [(r["code"], r["nav_date"], r.get("nav"), r.get("growth")) for r in rows]
    if batch:
        c.executemany("INSERT OR REPLACE INTO fund_nav(code,nav_date,nav,growth) VALUES(?,?,?,?)", batch)
        c.commit()
    return len(batch)


def upsert_fee(code: str, buy_tiers: Optional[list], redeem_tiers: Optional[list]) -> None:
    c = conn()
    c.execute("INSERT INTO fund_fee(code,buy_tiers,redeem_tiers,updated_at) VALUES(?,?,?,datetime('now','localtime')) "
              "ON CONFLICT(code) DO UPDATE SET buy_tiers=excluded.buy_tiers, redeem_tiers=excluded.redeem_tiers, "
              "updated_at=excluded.updated_at",
              (code, json.dumps(buy_tiers or [], ensure_ascii=False), json.dumps(redeem_tiers or [], ensure_ascii=False)))
    c.commit()


def upsert_purchase(rows: Iterable[dict]) -> int:
    c = conn()
    batch = [(r["code"], r.get("name"), r.get("ftype"), r.get("nav"), r.get("nav_date"),
              r.get("purchase_status"), r.get("redeem_status"), r.get("next_open"),
              r.get("min_amount"), r.get("daily_limit"), r.get("fee_rate")) for r in rows]
    if batch:
        c.executemany(
            "INSERT INTO fund_purchase(code,name,ftype,nav,nav_date,purchase_status,redeem_status,next_open,"
            "min_amount,daily_limit,fee_rate,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, ftype=excluded.ftype, nav=excluded.nav, "
            "nav_date=excluded.nav_date, purchase_status=excluded.purchase_status, redeem_status=excluded.redeem_status, "
            "next_open=excluded.next_open, min_amount=excluded.min_amount, daily_limit=excluded.daily_limit, "
            "fee_rate=excluded.fee_rate, updated_at=excluded.updated_at", batch)
        c.commit()
    return len(batch)


def set_meta(key: str, value) -> None:
    c = conn()
    c.execute("INSERT INTO arb_meta(key,value,updated_at) VALUES(?,?,datetime('now','localtime')) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
              (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value))
    c.commit()


def get_meta(key: str, default=None):
    c = conn()
    row = c.execute("SELECT value FROM arb_meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return row[0]


# ---------------- 读取 ----------------

def list_lofs() -> List[dict]:
    c = conn()
    return [dict(zip(("code", "name", "exchange"), r))
            for r in c.execute("SELECT code,name,exchange FROM lof_list ORDER BY code").fetchall()]


def last_daily_date(code: str) -> Optional[str]:
    c = conn()
    row = c.execute("SELECT MAX(date) FROM lof_daily WHERE code=?", (code,)).fetchone()
    return row[0] if row and row[0] else None


def last_nav_date(code: str) -> Optional[str]:
    c = conn()
    row = c.execute("SELECT MAX(nav_date) FROM fund_nav WHERE code=?", (code,)).fetchone()
    return row[0] if row and row[0] else None


def latest_snapshot() -> List[dict]:
    """每只 LOF 的「对齐快照」：价格与净值取**同一天**（最后一个两者都有的交易日）。

    为什么要对齐：净值通常 T 日 19:00 后才公布 —— 若直接拿「最新价 + 最新净值」，
    盘中/傍晚会得到「价格 T + 净值 T-1」的错配口径，折溢价率是错的。
    这里从最新价格日往回找第一个有净值的日子；找不到才退化为「价格 + ≤该日净值」并打标记。
    返回额外字段：aligned(是否同日)、lag_bars(相对最新价格日落后几个交易日)、price_latest_date。
    """
    c = conn()
    lofs = c.execute("SELECT code,name,exchange FROM lof_list ORDER BY code").fetchall()
    pur = {r[0]: r[1:] for r in c.execute(
        "SELECT code,purchase_status,redeem_status,min_amount,daily_limit,fee_rate,ftype FROM fund_purchase").fetchall()}
    fees = {r[0]: (r[1], r[2]) for r in c.execute("SELECT code,buy_tiers,redeem_tiers FROM fund_fee").fetchall()}
    out = []
    for code, name, exchange in lofs:
        px = c.execute("SELECT date, close, amount FROM lof_daily WHERE code=? ORDER BY date DESC LIMIT 25",
                       (code,)).fetchall()
        if not px:
            continue
        navs = dict(c.execute("SELECT nav_date, nav FROM fund_nav WHERE code=? ORDER BY nav_date DESC LIMIT 45",
                              (code,)).fetchall())
        aligned = None
        for i, (d, close, amt) in enumerate(px):
            if d in navs:
                aligned = (i, d, close, amt, navs[d])
                break
        if aligned:
            lag, price_date, price, amount, nav = aligned
            nav_date, ok = price_date, True
        else:
            lag, price_date, price, amount = 0, px[0][0], px[0][1], px[0][2]
            row = c.execute("SELECT nav_date, nav FROM fund_nav WHERE code=? AND nav_date<=? "
                            "ORDER BY nav_date DESC LIMIT 1", (code, price_date)).fetchone()
            nav_date, nav, ok = (row[0], row[1], False) if row else (None, None, False)
        p = pur.get(code) or (None, None, None, None, None, None)
        f = fees.get(code) or (None, None)
        out.append({
            "code": code, "name": name, "exchange": exchange,
            "price_date": price_date, "price": price, "amount": amount,
            "nav_date": nav_date, "nav": nav,
            "aligned": ok, "lag_bars": lag, "price_latest_date": px[0][0],
            "purchase_status": p[0], "redeem_status": p[1], "min_amount": p[2],
            "daily_limit": p[3], "fee_rate": p[4], "ftype": p[5],
            "redeem_tiers": f[1], "buy_tiers": f[0],
        })
    return out


def nav_series(code: str, days: int = 500) -> List[dict]:
    c = conn()
    rows = c.execute("SELECT nav_date, nav FROM fund_nav WHERE code=? ORDER BY nav_date DESC LIMIT ?",
                     (code, days)).fetchall()
    return [{"date": r[0], "nav": r[1]} for r in reversed(rows)]


def daily_series(code: str, days: int = 500) -> List[dict]:
    c = conn()
    rows = c.execute("SELECT date, close, amount FROM lof_daily WHERE code=? ORDER BY date DESC LIMIT ?",
                     (code, days)).fetchall()
    return [{"date": r[0], "close": r[1], "amount": r[2]} for r in reversed(rows)]


def premium_series(code: str, days: int = 250) -> List[dict]:
    """折溢价率序列（按净值日期对齐场内收盘；净值滞后则用 <= 该日的最近净值）。"""
    c = conn()
    px = c.execute("SELECT date, close FROM lof_daily WHERE code=? ORDER BY date DESC LIMIT ?",
                   (code, days)).fetchall()
    if not px:
        return []
    out = []
    for date, close in reversed(px):
        row = c.execute("SELECT nav_date, nav FROM fund_nav WHERE code=? AND nav_date<=? ORDER BY nav_date DESC LIMIT 1",
                        (code, date)).fetchone()
        if row and row[1]:
            out.append({"date": date, "close": close, "nav": row[1], "nav_date": row[0],
                        "premium_pct": round((close / row[1] - 1) * 100, 4)})
    return out


def stats() -> dict:
    c = conn()
    q = lambda sql: c.execute(sql).fetchone()[0]
    return {
        "lof_count": q("SELECT COUNT(*) FROM lof_list"),
        "daily_rows": q("SELECT COUNT(*) FROM lof_daily"),
        "daily_last": q("SELECT MAX(date) FROM lof_daily"),
        "nav_rows": q("SELECT COUNT(*) FROM fund_nav"),
        "nav_last": q("SELECT MAX(nav_date) FROM fund_nav"),
        "fee_count": q("SELECT COUNT(*) FROM fund_fee"),
        "purchase_count": q("SELECT COUNT(*) FROM fund_purchase"),
        "purchase_updated": q("SELECT MAX(updated_at) FROM fund_purchase"),
        # 当日净值还没公布（最新净值日 < 最新行情日）的基金数 —— 面板"已回退 N 只"用
        "nav_lagging": q("SELECT COUNT(*) FROM lof_list l WHERE "
                         "(SELECT MAX(date) FROM lof_daily WHERE code=l.code) > "
                         "(SELECT MAX(nav_date) FROM fund_nav WHERE code=l.code)"),
    }
