# -*- coding: utf-8 -*-
"""AI 操盘手长期记忆库 —— SQLite(data/ai_trader.db)。

独立于 sim_trade.db(账户/成交) 与 agent.db(网关)。只存操盘手自身状态：
  trader_profile   操盘手档案 (绑定账户 / 人设 / 风险约束 / 开关)
  trader_decision  每日决策 (思考 / 新闻 / 计划 / 执行结果 / 净值变化 / 复盘)
  trader_memory    长期记忆 (持仓逻辑 thesis / 经验教训 lesson / 观察 note)

每次调用自建连接(线程安全，适配 job 线程池)。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

from ..api.paths import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "ai_trader.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trader_profile(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT 'AI操盘手',
    account_id INTEGER NOT NULL,
    persona TEXT DEFAULT '',
    model TEXT DEFAULT '',
    risk_rules TEXT DEFAULT '{}',
    initial_capital REAL DEFAULT 100000,
    auto_execute INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS trader_decision(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    as_of TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    trigger TEXT NOT NULL DEFAULT 'manual',
    thinking TEXT DEFAULT '',
    reflection TEXT DEFAULT '',
    context TEXT DEFAULT '{}',
    news TEXT DEFAULT '[]',
    plan TEXT DEFAULT '[]',
    executions TEXT DEFAULT '[]',
    trace TEXT DEFAULT '[]',
    nav_before REAL,
    nav_after REAL,
    total_assets_before REAL,
    total_assets_after REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    UNIQUE(profile_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_trader_decision_profile
    ON trader_decision(profile_id, trade_date DESC);

CREATE TABLE IF NOT EXISTS trader_memory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    code TEXT DEFAULT '',
    content TEXT NOT NULL,
    decision_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_trader_memory_profile
    ON trader_memory(profile_id, active, created_at DESC);
"""


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def ensure_schema() -> None:
    con = get_conn()
    try:
        con.executescript(SCHEMA)
        # 轻量迁移：旧库补 trace 列 / profile.model 列
        cols = {r[1] for r in con.execute("PRAGMA table_info(trader_decision)")}
        if "trace" not in cols:
            con.execute("ALTER TABLE trader_decision ADD COLUMN trace TEXT DEFAULT '[]'")
        pcols = {r[1] for r in con.execute("PRAGMA table_info(trader_profile)")}
        if "model" not in pcols:
            con.execute("ALTER TABLE trader_profile ADD COLUMN model TEXT DEFAULT ''")
        con.commit()
    finally:
        con.close()


def _loads(v: Any, default):
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def _decision_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k, default in (("context", {}), ("news", []), ("plan", []),
                       ("executions", []), ("trace", [])):
        d[k] = _loads(d.get(k), default)
    return d


# ───────────────────────── profile ─────────────────────────

def get_profile(profile_id: Optional[int] = None) -> Optional[dict]:
    con = get_conn()
    try:
        if profile_id is None:
            row = con.execute("SELECT * FROM trader_profile ORDER BY id LIMIT 1").fetchone()
        else:
            row = con.execute("SELECT * FROM trader_profile WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["risk_rules"] = _loads(d.get("risk_rules"), {})
        return d
    finally:
        con.close()


def list_profiles() -> list:
    con = get_conn()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM trader_profile ORDER BY id")]
    finally:
        con.close()


def create_profile(account_id: int, name: str = "AI操盘手",
                   initial_capital: float = 100000.0, persona: str = "",
                   model: str = "", risk_rules: Optional[dict] = None) -> dict:
    con = get_conn()
    try:
        cur = con.execute(
            "INSERT INTO trader_profile (name, account_id, persona, model, risk_rules, initial_capital) "
            "VALUES (?,?,?,?,?,?)",
            (name, account_id, persona, model,
             json.dumps(risk_rules or {}, ensure_ascii=False), initial_capital))
        con.commit()
        pid = cur.lastrowid
    finally:
        con.close()
    return get_profile(pid)


def update_profile(profile_id: int, **fields) -> Optional[dict]:
    allowed = {"name", "persona", "risk_rules", "auto_execute", "enabled",
               "initial_capital", "account_id", "model"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "risk_rules" and isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        return get_profile(profile_id)
    args.append(profile_id)
    con = get_conn()
    try:
        con.execute(f"UPDATE trader_profile SET {', '.join(sets)} WHERE id=?", args)
        con.commit()
    finally:
        con.close()
    return get_profile(profile_id)


# ───────────────────────── decision ─────────────────────────

def get_decision(profile_id: int, trade_date: str) -> Optional[dict]:
    con = get_conn()
    try:
        row = con.execute(
            "SELECT * FROM trader_decision WHERE profile_id=? AND trade_date=?",
            (profile_id, trade_date)).fetchone()
        return _decision_to_dict(row) if row else None
    finally:
        con.close()


def get_decision_by_id(decision_id: int) -> Optional[dict]:
    con = get_conn()
    try:
        row = con.execute("SELECT * FROM trader_decision WHERE id=?", (decision_id,)).fetchone()
        return _decision_to_dict(row) if row else None
    finally:
        con.close()


def list_decisions(profile_id: int, limit: int = 60, offset: int = 0) -> list:
    con = get_conn()
    try:
        rows = con.execute(
            "SELECT * FROM trader_decision WHERE profile_id=? "
            "ORDER BY trade_date DESC, id DESC LIMIT ? OFFSET ?",
            (profile_id, limit, offset)).fetchall()
        return [_decision_to_dict(r) for r in rows]
    finally:
        con.close()


def upsert_decision(profile_id: int, trade_date: str, **fields) -> dict:
    """按 (profile_id, trade_date) 插入或更新。返回最新记录。"""
    con = get_conn()
    try:
        con.execute(
            "INSERT INTO trader_decision (profile_id, trade_date) VALUES (?,?) "
            "ON CONFLICT(profile_id, trade_date) DO NOTHING",
            (profile_id, trade_date))
        sets, args = [], []
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k}=?")
            args.append(v)
        if sets:
            args += [profile_id, trade_date]
            con.execute(
                f"UPDATE trader_decision SET {', '.join(sets)} WHERE profile_id=? AND trade_date=?",
                args)
        con.commit()
    finally:
        con.close()
    return get_decision(profile_id, trade_date)


# ───────────────────────── memory ─────────────────────────

def add_memory(profile_id: int, content: str, kind: str = "note",
               code: str = "", decision_id: Optional[int] = None) -> int:
    con = get_conn()
    try:
        # thesis=当前持仓逻辑；style=当前自我认知 —— 同类只保留最新一条 active，历史保留
        if kind in ("thesis", "style"):
            if kind == "thesis" and code:
                con.execute(
                    "UPDATE trader_memory SET active=0 "
                    "WHERE profile_id=? AND code=? AND kind='thesis' AND active=1",
                    (profile_id, code))
            elif kind == "style":
                con.execute(
                    "UPDATE trader_memory SET active=0 "
                    "WHERE profile_id=? AND kind='style' AND active=1",
                    (profile_id,))
        cur = con.execute(
            "INSERT INTO trader_memory (profile_id, kind, code, content, decision_id) "
            "VALUES (?,?,?,?,?)",
            (profile_id, kind, code, content, decision_id))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def list_memory(profile_id: int, active_only: bool = True, limit: int = 200,
                kind: Optional[str] = None) -> list:
    con = get_conn()
    try:
        sql = "SELECT * FROM trader_memory WHERE profile_id=?"
        args: list = [profile_id]
        if active_only:
            sql += " AND active=1"
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def set_memory_active(memory_id: int, active: bool) -> None:
    con = get_conn()
    try:
        con.execute("UPDATE trader_memory SET active=? WHERE id=?",
                    (1 if active else 0, memory_id))
        con.commit()
    finally:
        con.close()


def resolve_memory_by_code(profile_id: int, code: str, kind: str = "thesis") -> None:
    """某持仓清仓后，把该股的持仓逻辑标记为失效。"""
    con = get_conn()
    try:
        con.execute(
            "UPDATE trader_memory SET active=0 WHERE profile_id=? AND code=? AND kind=? AND active=1",
            (profile_id, code, kind))
        con.commit()
    finally:
        con.close()
