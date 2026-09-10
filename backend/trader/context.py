# -*- coding: utf-8 -*-
"""每日决策上下文构建。

把操盘手做决策需要的一切(账户/持仓/净值/市场/候选/新闻/历史记忆)整理成
一个紧凑的 dict，既注入 LLM 提示，也原样存入 trader_decision.context 供页面回看。

外部依赖(实时行情/新闻/选股)全部短超时 + 失败降级，绝不阻塞决策。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from ..api.paths import DATA_DIR, KLINE_DB
from ..trade_engine.engine import TradeEngine
from . import news as news_mod
from . import store

REGIME_PATH = os.path.join(DATA_DIR, "regime.json")
NEWS_DRIVEN_PATH = os.path.join(DATA_DIR, "news_driven.json")
HS300_PATH = os.path.join(DATA_DIR, "hs300.json")


# ───────────────────────── 价格 ─────────────────────────

def _kline_latest_close(codes: List[str]) -> dict:
    out = {}
    try:
        con = sqlite3.connect(KLINE_DB)
        con.row_factory = sqlite3.Row
        for c in codes:
            row = con.execute(
                "SELECT date, close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1",
                (c,)).fetchone()
            if row:
                out[c] = {"price": float(row["close"]), "date": str(row["date"]), "src": "kline"}
        con.close()
    except Exception:
        pass
    return out


def refresh_prices(codes: List[str]) -> dict:
    """批量取价：优先实时(新浪)，失败回退 kline 最新收盘。返回 {code: {price,date,src}}。"""
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    out = {}
    try:
        from ..data_manager import fetch_realtime_prices
        for r in fetch_realtime_prices(codes) or []:
            p = r.get("price")
            if p:
                out[str(r.get("code"))] = {"price": float(p),
                                           "change_pct": float(r.get("change_pct") or 0),
                                           "src": "realtime"}
    except Exception:
        pass
    missing = [c for c in codes if c not in out]
    if missing:
        out.update(_kline_latest_close(missing))
    return out


def _days_since(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    s = str(date_str).replace("-", "")[:8]
    try:
        d = datetime.strptime(s, "%Y%m%d")
    except Exception:
        return None
    return (datetime.now() - d).days


# ───────────────────────── 账户/持仓 ─────────────────────────

def build_account_block(account_id: int) -> dict:
    engine = TradeEngine()
    positions = engine.get_positions(account_id)
    prices = refresh_prices([p["code"] for p in positions])
    if prices:
        engine.update_all_prices(
            account_id, {c: v["price"] for c, v in prices.items() if v.get("price")})
    s = engine.get_summary(account_id) or {}
    pos_rows = []
    for p in engine.get_positions(account_id):
        px = prices.get(p["code"], {})
        pos_rows.append({
            "code": p["code"], "name": p["name"], "qty": p["qty"],
            "cost_price": round(float(p["cost_price"]), 3),
            "price": round(float(p["current_price"]), 3),
            "market_value": round(float(p["market_value"]), 2),
            "float_pnl": round(float(p["float_pnl"]), 2),
            "float_pnl_pct": round(
                (float(p["current_price"]) / float(p["cost_price"]) - 1) * 100, 2)
            if p["cost_price"] else 0.0,
            "last_buy_date": p.get("last_buy_date") or "",
            "holding_days": _days_since(p.get("last_buy_date")),
            "price_src": px.get("src", ""),
        })
    pos_rows.sort(key=lambda x: x["market_value"], reverse=True)
    pending = [{
        "order_id": o["id"], "code": o["code"], "name": o["name"],
        "side": o["side"], "price": round(float(o["price"]), 3),
        "qty": o["qty"], "created_at": o["created_at"],
    } for o in engine.get_orders(account_id, "pending")]
    nav = engine.get_nav_history(account_id) or {}
    nav_rows = [{"date": d, "nav": n, "total_assets": ta}
                for d, n, ta in zip(nav.get("dates", []), nav.get("nav", []),
                                    nav.get("total_assets", []))]
    return {
        "summary": {
            "total_assets": round(float(s.get("total_assets", 0)), 2),
            "balance": round(float(s.get("balance", 0)), 2),
            "frozen": round(float(s.get("frozen", 0)), 2),
            "market_value": round(float(s.get("market_value", 0)), 2),
            "float_pnl": round(float(s.get("float_pnl", 0)), 2),
            "total_profit": round(float(s.get("total_profit", 0)), 2),
            "total_profit_pct": round(float(s.get("total_profit_pct", 0)), 2),
            "initial_capital": round(float(s.get("initial_capital", 0)), 2),
            "positions": s.get("positions", 0),
            "pending_orders": s.get("pending_orders", 0),
        },
        "positions": pos_rows,
        "pending_orders": pending,
        "nav_history": nav_rows[-15:],
        "prices": prices,
    }


# ───────────────────────── 市场 ─────────────────────────

def _prices_for(codes: List[str]) -> dict:
    return refresh_prices(codes)


def _hs300_trend() -> dict:
    """沪深300 近端趋势（1/5/20 日涨跌）。"""
    try:
        with open(HS300_PATH, encoding="utf-8") as f:
            d = json.load(f)
        closes = [float(x) for x in d.get("closes") or []]
        dates = d.get("dates") or []
        if len(closes) < 2:
            return {}
        last = closes[-1]
        def chg(n):
            return round((last / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None
        return {"code": d.get("code"), "name": d.get("name"),
                "date": dates[-1] if dates else None, "close": round(last, 2),
                "chg_1d": chg(1), "chg_5d": chg(5), "chg_20d": chg(20)}
    except Exception:
        return {}


def build_market_block() -> dict:
    out = {}
    try:
        with open(REGIME_PATH, encoding="utf-8") as f:
            r = json.load(f)
        out["regime"] = {
            "as_of": r.get("as_of"), "regime": r.get("regime_cn") or r.get("regime"),
            "suggest_strategy": r.get("suggest_strategy"),
            "sys_risk": r.get("sys_risk", {}),
            "score": {k: r.get("score", {}).get(k) for k in ("px", "ma20", "ma60", "drawdown")},
        }
    except Exception:
        out["regime"] = {}
    out["hs300"] = _hs300_trend()
    return out


def build_candidates_block(top_n: int = 12) -> dict:
    """候选池（实时）：多因子评分 Top N + 事件驱动池 + 完整选股链路口径。"""
    from .selection import build_snapshot
    return build_snapshot(None, top_n=top_n, with_events=True)


# ───────────────────────── 新闻 ─────────────────────────

def build_news_block(positions: List[dict], picks: List[dict],
                     per_stock: int = 3, max_stocks: int = 6) -> dict:
    market = news_mod.market_news(limit=20)
    watch = []
    seen = set()
    for item in list(positions) + list(picks):
        c = str(item.get("code") or "")
        if not c or c in seen:
            continue
        seen.add(c)
        watch.append({"code": c, "name": item.get("name") or ""})
        if len(watch) >= max_stocks:
            break
    stock_items = []
    for w in watch:
        rows = news_mod.stock_news(w["code"], w["name"], limit=per_stock)
        if rows:
            stock_items.append({"code": w["code"], "name": w["name"], "news": rows})
    return {"market": market, "stocks": stock_items}


# ───────────────────────── 历史记忆 ─────────────────────────

def build_memory_block(profile_id: int, positions: List[dict], limit: int = 8,
                       account_id: Optional[int] = None,
                       as_of: Optional[str] = None) -> dict:
    decisions = store.list_decisions(profile_id, limit=limit)
    history = []
    for d in decisions:
        if d.get("status") != "done":
            continue
        history.append({
            "date": d["trade_date"],
            "thinking": (d.get("thinking") or "")[:600],
            "reflection": (d.get("reflection") or "")[:300],
            "orders": d.get("plan") or [],
            "executions": d.get("executions") or [],
            "nav_after": d.get("nav_after"),
        })
    mem = store.list_memory(profile_id, active_only=True, limit=80)
    theses = {}
    style = ""
    for m in mem:
        if m["kind"] == "thesis" and m.get("code") and m["code"] not in theses:
            theses[m["code"]] = m["content"]
        elif m["kind"] == "style" and not style:
            style = m["content"]
    held = [{"code": p["code"], "name": p["name"], "thesis": theses.get(p["code"], "")}
            for p in positions]
    perf = {}
    if account_id:
        try:
            from .performance import performance_block
            perf = performance_block(int(profile_id), int(account_id), as_of=as_of)
        except Exception:
            perf = {}
    return {
        "self_style": style,
        "recent_decisions": history,
        "holding_theses": held,
        "your_performance": perf,
        "notes": [{"kind": m["kind"], "code": m.get("code") or "",
                   "content": m["content"], "at": m["created_at"]}
                  for m in mem if m["kind"] not in ("thesis", "style")][:20],
    }


# ───────────────────────── 汇总 ─────────────────────────

def build_daily_context(profile: dict, with_candidates: bool = True,
                        with_news: bool = True) -> dict:
    """构建一次决策的完整上下文。"""
    account_id = int(profile["account_id"])
    acct = build_account_block(account_id)
    market = build_market_block()
    cands = build_candidates_block() if with_candidates else {"picks": [], "events": []}
    news_block = (build_news_block(acct["positions"], cands.get("picks", []))
                  if with_news else {"market": [], "stocks": []})
    memory = build_memory_block(int(profile["id"]), acct["positions"],
                                account_id=int(profile["account_id"]))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": {
            "name": profile.get("name"), "persona": profile.get("persona"),
            "risk_rules": profile.get("risk_rules") or {},
            "initial_capital": profile.get("initial_capital"),
        },
        "account": acct["summary"],
        "positions": acct["positions"],
        "pending_orders": acct["pending_orders"],
        "nav_history": acct["nav_history"],
        "market": market,
        "candidates": cands,
        "news": news_block,
        "memory": memory,
        "prices": acct["prices"],
    }
