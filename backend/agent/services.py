# -*- coding: utf-8 -*-
"""Agent Gateway 业务服务层 — 网关直接复用现有 strategy/macro/trade_engine 服务。

薄层：R(宏观看板/目录/因子/K线)/W(声明式策略CRUD/watchlist)/B(异步回测)/T(paper下单)。
宏观不重新抓数，改从 data/macro.db 读取最近序列再合成 regime(无网络依赖)。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

from ..strategy.spec import StrategySpec
from ..strategy import catalog as catalog_mod
from ..strategy.data import load_klines, stock_name
from ..strategy import backtest as bt
from ..macro import catalog as macro_catalog
from ..macro.features import compute_regime
from ..trade_engine.engine import TradeEngine
from ..trade_engine import schema as trade_schema
from . import store

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MACRO_DB = os.path.join(_PROJECT_DIR, "data", "macro.db")


# ────────────────────────── 宏观 ─────────────────────────────────────
def macro_regime() -> dict:
    """从 macro.db 读最近序列 → 合成 regime。返回 {feats, category, as_of, freshness}。"""
    con = sqlite3.connect(MACRO_DB)
    con.row_factory = sqlite3.Row
    try:
        series_map = {}
        for ind in macro_catalog.INDICATORS:
            key = ind["key"]
            rows = con.execute(
                "SELECT date, value FROM series WHERE key=? ORDER BY date DESC LIMIT 70",
                (key,)).fetchall()
            series_map[key] = list(reversed([(r["date"], r["value"]) for r in rows]))
        latest = con.execute("SELECT MAX(date) AS d FROM series").fetchone()["d"]
    finally:
        con.close()

    feats = compute_regime(series_map)
    cat = feats.pop("_category", {})
    # 新鲜度：最新日期距今天数
    freshest = None
    for f in feats.values():
        if f.get("latest_date") and (freshest is None or f["latest_date"] > freshest):
            freshest = f["latest_date"]
    from datetime import datetime
    freshness_days = None
    if freshest:
        try:
            freshness_days = (datetime.now() - datetime.strptime(str(freshest), "%Y%m%d")).days
        except Exception:
            freshness_days = None
    return {
        "as_of": freshest,
        "freshness_days": freshness_days,
        "overall": cat.get("overall", ""),
        "categories": cat,
        "indicators": feats,
    }


def macro_indicators(category: Optional[str] = None) -> list[dict]:
    return macro_catalog.indicators(category)


# ────────────────────────── 目录 / 标的池 ─────────────────────────────
def catalog_stats() -> dict:
    return catalog_mod.stats()


def catalog_sectors() -> list[str]:
    return catalog_mod.sectors()


def catalog_select(**kw) -> list[dict]:
    return catalog_mod.select(**kw)


def catalog_describe(code: str):
    return catalog_mod.describe(code)


def catalog_search(kw: str, limit: int = 30) -> list[dict]:
    return catalog_mod.search(kw, limit)


def catalog_board_overview(limit: int = 20, btype: Optional[str] = None) -> list[dict]:
    return catalog_mod.board_overview(limit, btype)


def catalog_leader_of(sector: str):
    return catalog_mod.leader_of(sector)


# ────────────────────────── 因子 / K线 ───────────────────────────────
FACTORS = [
    {"key": "CLOSE", "desc": "收盘价", "type": "price"},
    {"key": "OPEN", "desc": "开盘价", "type": "price"},
    {"key": "HIGH", "desc": "最高价", "type": "price"},
    {"key": "LOW", "desc": "最低价", "type": "price"},
    {"key": "VOLUME", "desc": "成交量", "type": "volume"},
    {"key": "AMOUNT", "desc": "成交额", "type": "volume"},
    {"key": "MA5", "desc": "5日均线", "type": "ma"},
    {"key": "MA10", "desc": "10日均线", "type": "ma"},
    {"key": "MA20", "desc": "20日均线", "type": "ma"},
    {"key": "MA60", "desc": "60日均线", "type": "ma"},
    {"key": "MACD_DIF", "desc": "MACD DIF", "type": "macd"},
    {"key": "MACD_DEA", "desc": "MACD DEA", "type": "macd"},
    {"key": "MACD_HIST", "desc": "MACD 柱", "type": "macd"},
    {"key": "RSI6", "desc": "RSI(6)", "type": "oscillator"},
    {"key": "RSI14", "desc": "RSI(14)", "type": "oscillator"},
    {"key": "BOLL_UPPER", "desc": "布林上轨", "type": "boll"},
    {"key": "BOLL_MID", "desc": "布林中轨", "type": "boll"},
    {"key": "BOLL_LOWER", "desc": "布林下轨", "type": "boll"},
    {"key": "CHANGE_PCT", "desc": "涨跌幅(小数)", "type": "derived"},
    {"key": "VOL_RATIO_5", "desc": "5日量比", "type": "derived"},
    {"key": "PRICE_POS_20", "desc": "20日价格位置(0~1)", "type": "derived"},
    {"key": "MA5_GT_MA10", "desc": "MA5>MA10(1/0)", "type": "boolean"},
    {"key": "MA10_GT_MA20", "desc": "MA10>MA20(1/0)", "type": "boolean"},
    {"key": "CLOSE_GT_MA20", "desc": "收盘>MA20(1/0)", "type": "boolean"},
    {"key": "MA5_CROSS_UP_MA10", "desc": "MA5金叉MA10(1/0)", "type": "boolean"},
    {"key": "MA5_CROSS_DOWN_MA10", "desc": "MA5死叉MA10(1/0)", "type": "boolean"},
    {"key": "MACD_CROSS_UP", "desc": "MACD金叉(1/0)", "type": "boolean"},
    {"key": "MACD_CROSS_DOWN", "desc": "MACD死叉(1/0)", "type": "boolean"},
]


def factors_list(category: Optional[str] = None) -> list[dict]:
    if category:
        return [f for f in FACTORS if f["type"] == category]
    return FACTORS


def klines(code: str, days: int = 180) -> dict:
    from ..indicators import enrich_kline
    kd, warns = load_klines(code, limit=days)
    enriched = enrich_kline(kd) if kd else []
    return {"code": code, "name": stock_name(code), "bars": len(kd),
            "warnings": warns, "data": enriched}


# ────────────────────────── 组合 / watchlist ─────────────────────────
def portfolio_positions(agent_id: str) -> dict:
    trade_schema.ensure_tables()
    engine = TradeEngine()
    accounts = engine.list_accounts()
    out = []
    for a in accounts:
        if not a.get("is_active"):
            continue
        pos = engine.get_positions(a["id"])
        for p in pos:
            p["account"] = a["name"]
            out.append(p)
    return {"accounts": [a for a in accounts if a.get("is_active")], "positions": out}


def watchdog() -> dict:
    return {}


# ────────────────────────── 声明式策略 CRUD ───────────────────────────
def _norm_contract(raw: Any) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


def create_strategy(agent_token_id: int, agent_id: str, contract: dict) -> dict:
    spec = StrategySpec.from_dict(contract)
    spec.validate()
    store.ensure_schema()
    con = store.get_conn()
    try:
        cur = con.execute(
            "INSERT INTO agent_strategies(agent_token_id,agent_id,name,description,contract,status)"
            " VALUES(?,?,?,?,?,?)",
            (agent_token_id, agent_id, spec.name, spec.description,
             json.dumps(spec.to_dict(), ensure_ascii=False, default=str), "draft"))
        con.commit()
        sid = cur.lastrowid
    finally:
        con.close()
    return {"id": sid, **spec.to_dict(), "status": "draft"}


def _strategy_rows(agent_id: str, sid: Optional[int] = None) -> list[dict]:
    con = store.get_conn()
    try:
        if sid is not None:
            rows = con.execute(
                "SELECT * FROM agent_strategies WHERE id=? AND agent_id=?", (sid, agent_id)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM agent_strategies WHERE agent_id=? ORDER BY id DESC", (agent_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["contract"] = json.loads(d["contract"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        con.close()


def list_strategies(agent_id: str) -> list[dict]:
    return _strategy_rows(agent_id)


def get_strategy(agent_id: str, sid: int):
    rows = _strategy_rows(agent_id, sid)
    return rows[0] if rows else None


def update_strategy(agent_id: str, sid: int, contract: dict) -> dict:
    spec = StrategySpec.from_dict(contract)
    spec.validate()
    con = store.get_conn()
    try:
        cur = con.execute(
            "UPDATE agent_strategies SET name=?,description=?,contract=?,updated_at=datetime('now','localtime') "
            "WHERE id=? AND agent_id=?",
            (spec.name, spec.description, json.dumps(spec.to_dict(), ensure_ascii=False, default=str),
             sid, agent_id))
        con.commit()
        if cur.rowcount == 0:
            return None
    finally:
        con.close()
    return get_strategy(agent_id, sid)


def delete_strategy(agent_id: str, sid: int) -> bool:
    con = store.get_conn()
    try:
        cur = con.execute("DELETE FROM agent_strategies WHERE id=? AND agent_id=?", (sid, agent_id))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


# ────────────────────────── watchlist ────────────────────────────────
def watchlist_add(agent_token_id: int, agent_id: str, code: str, name: str = "") -> dict:
    store.ensure_schema()
    con = store.get_conn()
    try:
        con.execute("INSERT OR IGNORE INTO agent_watchlist(agent_token_id,agent_id,code,name) VALUES(?,?,?,?)",
                    (agent_token_id, agent_id, code, name or code))
        con.commit()
    finally:
        con.close()
    return {"code": code, "name": name or code, "added": True}


def watchlist_remove(agent_id: str, code: str) -> bool:
    con = store.get_conn()
    try:
        cur = con.execute("DELETE FROM agent_watchlist WHERE agent_id=? AND code=?", (agent_id, code))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def watchlist_list(agent_id: str) -> list[dict]:
    con = store.get_conn()
    try:
        return store.rows_to_list(con.execute(
            "SELECT code,name,created_at FROM agent_watchlist WHERE agent_id=? ORDER BY id DESC",
            (agent_id,)).fetchall())
    finally:
        con.close()


# ────────────────────────── 异步回测(B) ──────────────────────────────
def _load_price(code: str):
    """取单标的最近收盘价(做 paper 单、回测显示用)。"""
    kd, _ = load_klines(code, limit=1)
    return kd[-1]["close"] if kd else None


def build_backtest_runner(agent_id: str, strategy_id: int):
    """闭包：异步 job runner，签名 runner(payload) -> metrics 字典。"""

    def runner(payload: dict):
        strategy = get_strategy(agent_id, strategy_id)
        if not strategy:
            return {"error": "strategy not found"}
        contract = strategy["contract"] if "contract" in strategy else _norm_contract(payload.get("contract"))
        params = dict(payload.get("params") or {})
        if "initial_balance" not in params:
            params["initial_balance"] = 100000.0

        spec = StrategySpec.from_dict({**contract, "params": params})
        spec.validate()
        resolved = spec.resolve_universe()
        if not resolved["codes"]:
            return {"error": "universe 解析为空", "universe": resolved}
        code = resolved["codes"][0]
        name = stock_name(code)
        kd, warns = load_klines(code, limit=params.get("bars", 1200))
        if not kd:
            return {"error": "无K线数据", "code": code, "warnings": warns}
        res = bt.run_backtest(spec, kd)
        m = res.metrics
        return {
            "code": code, "name": name, "spec_name": spec.name,
            "range": {"from": kd[0]["date"], "to": kd[-1]["date"], "bars": len(kd)},
            "metrics": m,
            "trades": res.trades[-20:],
            "errors": res.errors[-10:],
            "warnings": warns,
            "equity_tail": res.equity_curve[-40:],
        }

    return runner


def run_backtest_now(agent_id: str, strategy_id: int, params: Optional[dict] = None) -> dict:
    """同步跑一次回测(供 smoke/直调)。"""
    return build_backtest_runner(agent_id, strategy_id)({"params": params or {}})


# ────────────────────────── paper 下单(T, paper-only) ────────────────
def paper_order(agent_token_id: int, agent_id: str, payload: dict, paper_only: bool = True) -> dict:
    """经 TradeEngine 走模拟撮合；强制 paper-only(本部署无实盘路径)。"""
    if not paper_only:
        return {"error": "本部署未启用实盘交易(仅 paper)", "code": "live_not_enabled"}
    trade_schema.ensure_tables()
    engine = TradeEngine()
    code = str(payload.get("code", "")).strip()
    side = str(payload.get("side", "")).strip().lower()
    if not code or side not in ("buy", "sell"):
        return {"error": "需要 code 且 side 为 buy/sell"}
    qty = int(payload.get("qty", 0) or 0)
    order_type = str(payload.get("order_type", "market")).lower()
    limit_price = float(payload.get("price") or 0.0)
    current_price = float(payload.get("current_price") or 0.0) or _load_price(code) or 0.0
    name = payload.get("name") or stock_name(code)

    account_id = int(payload.get("account_id") or 0)
    accounts = engine.list_accounts()
    if account_id == 0:
        active = [a for a in accounts if a.get("is_active")]
        if not active:
            # 首单自动建一个模拟账户
            acc = engine.create_account("paper-default", 100000.0)
            account_id = acc["id"] if isinstance(acc, dict) else acc
        else:
            account_id = active[0]["id"]

    if order_type == "market":
        order, trade = engine.place_order(account_id, code, name, side, "market", 0, qty,
                                          current_price=current_price)
    else:
        order, trade = engine.place_order(account_id, code, name, side, "limit", limit_price, qty,
                                          current_price=current_price)

    if order is None:
        return {"error": trade, "code": "order_rejected"}
    return {
        "order_id": order["id"] if isinstance(order, dict) else None,
        "account_id": account_id, "code": code, "name": name, "side": side,
        "order_type": order_type, "status": order.get("status") if isinstance(order, dict) else None,
        "filled_price": order.get("filled_price") if isinstance(order, dict) else None,
        "note": "paper",
    }
