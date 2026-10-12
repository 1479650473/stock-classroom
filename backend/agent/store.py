# -*- coding: utf-8 -*-
"""agent 网关数据存储 — SQLite(data/agent.db)。

独立于 stock_cache.db / kline.db / sim_trade.db，只存网关自身状态：
agent_tokens / agent_audit / agent_jobs / agent_idempotency / agent_strategies / agent_watchlist。
每次调用自建连接(线程安全，适配 ThreadPoolExecutor 异步 job)。
"""
import os
import sqlite3

from ..api.paths import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "agent.db")


def get_db_path() -> str:
    return DB_PATH


def get_conn():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tokens(
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    scopes TEXT NOT NULL DEFAULT 'R',
    paper_only INTEGER NOT NULL DEFAULT 1,
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    markets TEXT NOT NULL DEFAULT '',
    instruments TEXT NOT NULL DEFAULT '',
    expires_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_agent ON agent_tokens(agent_id);

CREATE TABLE IF NOT EXISTS agent_audit(
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    agent_token_id INTEGER,
    agent_id TEXT,
    route TEXT,
    scope_class TEXT,
    status TEXT,
    idempotency_key TEXT,
    request_summary TEXT,
    response_code INTEGER
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_agent ON agent_audit(agent_id, ts DESC);

CREATE TABLE IF NOT EXISTS agent_jobs(
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    agent_token_id INTEGER,
    agent_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    request TEXT,
    result TEXT,
    progress TEXT,
    error TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_agent ON agent_jobs(agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_idempotency(
    id INTEGER PRIMARY KEY,
    agent_token_id INTEGER,
    method TEXT,
    route TEXT,
    idem_key TEXT,
    request_hash TEXT,
    job_id TEXT,
    status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(agent_token_id, method, route, idem_key)
);
CREATE INDEX IF NOT EXISTS idx_agent_idem_key ON agent_idempotency(idem_key);

CREATE TABLE IF NOT EXISTS agent_strategies(
    id INTEGER PRIMARY KEY,
    agent_token_id INTEGER,
    agent_id TEXT,
    name TEXT,
    description TEXT,
    contract TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_agent_strategies_agent ON agent_strategies(agent_id, id DESC);

CREATE TABLE IF NOT EXISTS agent_watchlist(
    id INTEGER PRIMARY KEY,
    agent_token_id INTEGER,
    agent_id TEXT,
    code TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(agent_token_id, code)
);
"""


def ensure_schema():
    """创建网关表(幂等)。"""
    con = get_conn()
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()
