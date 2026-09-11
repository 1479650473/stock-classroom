# -*- coding: utf-8 -*-
"""因子挖掘结果落库（data/alpha.db）。

表：
    alpha_run      一次挖掘/滚动验证运行（参数、元信息、汇总、fitness 曲线、状态）
    alpha_formula  该次运行产出的公式（token 序列、可读公式、训练/样本外指标、是否保留）
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from ..api.paths import DATA_DIR

DB_PATH = os.path.join(str(DATA_DIR), "alpha.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alpha_run(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'mine',
    status TEXT NOT NULL DEFAULT 'running',
    params TEXT DEFAULT '{}',
    meta TEXT DEFAULT '{}',
    summary TEXT DEFAULT '{}',
    history TEXT DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS alpha_formula(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    fold INTEGER DEFAULT 0,
    rank INTEGER DEFAULT 0,
    tokens TEXT DEFAULT '[]',
    formula TEXT DEFAULT '',
    train_metrics TEXT DEFAULT '{}',
    oos_metrics TEXT DEFAULT '{}',
    kept INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_alpha_formula_run ON alpha_formula(run_id, rank);
"""


def _con() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def ensure_schema() -> None:
    con = _con()
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()


def _loads(v: Any, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def create_run(kind: str, params: Dict) -> int:
    ensure_schema()
    con = _con()
    try:
        cur = con.execute("INSERT INTO alpha_run(kind, params) VALUES (?,?)",
                          (kind, json.dumps(params or {}, ensure_ascii=False)))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def finish_run(run_id: int, status: str, meta: Optional[Dict] = None,
               summary: Optional[Dict] = None, history: Optional[list] = None,
               error: str = "") -> None:
    con = _con()
    try:
        sets, args = ["status=?", "finished_at=datetime('now','localtime')"], [status]
        if meta is not None:
            sets.append("meta=?")
            args.append(json.dumps(meta, ensure_ascii=False))
        if summary is not None:
            sets.append("summary=?")
            args.append(json.dumps(summary, ensure_ascii=False))
        if history is not None:
            sets.append("history=?")
            args.append(json.dumps(history, ensure_ascii=False))
        if error:
            sets.append("error=?")
            args.append(error[:400])
        args.append(int(run_id))
        con.execute(f"UPDATE alpha_run SET {', '.join(sets)} WHERE id=?", args)
        con.commit()
    finally:
        con.close()


def add_formula(run_id: int, rank: int, tokens: list, formula: str,
                train: Optional[Dict] = None, oos: Optional[Dict] = None,
                kept: int = 1, fold: int = 0) -> int:
    con = _con()
    try:
        cur = con.execute(
            "INSERT INTO alpha_formula(run_id, fold, rank, tokens, formula, train_metrics, oos_metrics, kept)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (int(run_id), int(fold), int(rank), json.dumps(tokens or [], ensure_ascii=False),
             str(formula or "")[:600], json.dumps(train or {}, ensure_ascii=False),
             json.dumps(oos or {}, ensure_ascii=False), int(kept)))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def _run_to_dict(row: sqlite3.Row) -> Dict:
    d = dict(row)
    for k, default in (("params", {}), ("meta", {}), ("summary", {}), ("history", [])):
        d[k] = _loads(d.get(k), default)
    return d


def _formula_to_dict(row: sqlite3.Row) -> Dict:
    d = dict(row)
    for k, default in (("tokens", []), ("train_metrics", {}), ("oos_metrics", {})):
        d[k] = _loads(d.get(k), default)
    return d


def delete_run(run_id: int) -> int:
    """删除一次运行及其公式（导入/测试记录清理用）。"""
    con = _con()
    try:
        n = con.execute("DELETE FROM alpha_formula WHERE run_id=?", (int(run_id),)).rowcount
        con.execute("DELETE FROM alpha_run WHERE id=?", (int(run_id),))
        con.commit()
        return int(n)
    finally:
        con.close()


def list_runs(limit: int = 20, kind: Optional[str] = None) -> List[Dict]:
    ensure_schema()
    con = _con()
    try:
        sql = "SELECT * FROM alpha_run"
        args: list = []
        if kind:
            sql += " WHERE kind=?"
            args.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        return [_run_to_dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def get_run(run_id: int, with_formulas: bool = True) -> Optional[Dict]:
    ensure_schema()
    con = _con()
    try:
        row = con.execute("SELECT * FROM alpha_run WHERE id=?", (int(run_id),)).fetchone()
        if row is None:
            return None
        d = _run_to_dict(row)
        if with_formulas:
            d["formulas"] = [
                _formula_to_dict(r) for r in con.execute(
                    "SELECT * FROM alpha_formula WHERE run_id=? ORDER BY rank DESC, id", (int(run_id),))]
        return d
    finally:
        con.close()
