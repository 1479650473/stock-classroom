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


def _screen_dimensions() -> dict:
    try:
        from .screen import DIMENSIONS
        return DIMENSIONS
    except Exception:
        return {}


def build_candidates_block(top_n: int = 12, weights=None, source: str = "scorecard") -> dict:
    """候选池（实时）：多因子评分 Top N + 事件驱动池 + 完整选股链路口径。

    source='composite' 时改用固定权重因子组合（-1日反转/-5日反转/-远离60日高点/-小市值）。
    """
    from .selection import build_snapshot
    return build_snapshot(None, top_n=top_n, with_events=True, weights=weights, source=source)


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

def _ops_summary(plan: list, executions: list) -> str:
    """把当日委托压成一行（复用：历史日子不需要逐笔明细）。"""
    if not plan:
        return "无操作"
    parts = []
    for i, o in enumerate(plan[:6]):
        side = "买" if o.get("side") == "buy" else "卖"
        name = o.get("name") or o.get("code")
        res = ""
        try:
            e = (executions or [])[i] or {}
            res = "✓" if e.get("ok") else ("✗" if e.get("detail") else "")
        except Exception:
            res = ""
        parts.append(f"{side}{name}{res}")
    return "、".join(parts) + ("…" if len(plan) > 6 else "")


def build_memory_block(profile_id: int, positions: List[dict], limit: int = 10,
                       account_id: Optional[int] = None,
                       as_of: Optional[str] = None) -> dict:
    """历史决策：**近 3 日详细 + 更早压缩成一行**（增量复用思路）。

    每天都是一次全新对话，无法"只传增量"，所以省 token 的正确做法是压缩：
    近期保留思考/复盘/委托（模型需要延续判断），远期只留"日期 + 净值 + 操作 + 复盘一句"，
    该信息量足以让模型知道自己做过什么、结果如何，而 token 只占原来的 ~15%。
    """
    DETAIL_DAYS = 3
    decisions = [d for d in store.list_decisions(profile_id, limit=limit)
                 if d.get("status") == "done"]
    history = []
    for i, d in enumerate(decisions):
        if i < DETAIL_DAYS:
            history.append({
                "date": d["trade_date"],
                "thinking": (d.get("thinking") or "")[:520],
                "reflection": (d.get("reflection") or "")[:260],
                "orders": d.get("plan") or [],
                "executions": d.get("executions") or [],
                "nav_after": d.get("nav_after"),
                "outlook": (d.get("outlook") or {}).get("direction") if isinstance(d.get("outlook"), dict) else None,
                "outlook_hit": (d.get("outlook_score") or {}).get("hit") if isinstance(d.get("outlook_score"), dict) else None,
            })
        else:
            history.append({
                "date": d["trade_date"],
                "ops": _ops_summary(d.get("plan") or [], d.get("executions") or []),
                "nav_after": d.get("nav_after"),
                "reflection": (d.get("reflection") or "")[:90],
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
        "history_note": "近 3 个交易日逐条详细（含委托与结果）；更早的日子只给摘要"
                        "（日期/操作/净值/复盘一句）——需要细节用工具查或问自己写下的记忆。",
        "recent_decisions": history,
        "holding_theses": held,
        "your_performance": perf,
        "discipline_rules": _rules_block(int(profile_id), as_of),
        "notes": [{"kind": m["kind"], "code": m.get("code") or "",
                   "content": (m["content"] or "")[:220], "at": m["created_at"]}
                  for m in mem if m["kind"] not in ("thesis", "style", "rule")][:12],
    }


def _rules_block(profile_id: int, as_of: Optional[str] = None) -> list:
    """当前生效的纪律规则（自省结论 → 系统强制执行，模型必须知道）。

    系统恒定规则也一并告诉模型（不是模型可改的），否则它会反复试探同一个被拒动作。
    """
    try:
        from .discipline import active_rules, describe_rules, protection_rules
        out = [x["text"] for x in describe_rules(active_rules(int(profile_id), as_of))]
        p = protection_rules(int(profile_id), as_of)
        out.append(f"系统恒定规则：卖出后 {int(p.get('sell_reentry_cooldown') or 0)} 个交易日内"
                   f"不得买回同一只；限价挂单 {int(p.get('pending_expiry_days') or 0)} 个交易日"
                   f"未成交将由系统撤销；浮亏 {float(p.get('stop_loss_pct') or 0):g}% 触发兜底止损")
        return out
    except Exception:
        return []


# ───────────────────────── 汇总 ─────────────────────────

def build_daily_context(profile: dict, with_candidates: bool = True,
                        with_news: bool = True) -> dict:
    """构建一次决策的完整上下文。"""
    account_id = int(profile["account_id"])
    weights = (profile.get("meta") or {}).get("weights")
    acct = build_account_block(account_id)
    market = build_market_block()
    meta = (profile or {}).get("meta", {}) if isinstance(profile, dict) else {}
    selection = str(meta.get("selection") or "self")          # self=模型自己选股（默认）
    scoring = str(meta.get("scoring") or "scorecard")
    if with_candidates and selection == "self":
        # 自主选股模式：不预先给候选池，避免"在别人选好的股里挑"；只给检索工具说明与市场概览。
        cands = {"picks": [], "events": [], "source": "self", "mode": "self",
                 "chain": "自主选股：模型用 screen_stocks / get_stock_factors 自行检索市场",
                 "scope_note": {
                     "口径": "自主选股（无预置候选池）",
                     "可用维度": {k: f"{v[0]}（{v[1]}）" for k, v in _screen_dimensions().items()},
                     "说明": "先想清楚你的选股标准，再用 screen_stocks 按维度筛选与排序；"
                             "对候选再用 get_stock_factors / get_stock_price / K线 验证后下单。",
                 }}
    else:
        cands = (build_candidates_block(weights=weights, source=scoring)
                 if with_candidates else {"picks": [], "events": []})
    news_block = (build_news_block(acct["positions"], cands.get("picks", []))
                  if with_news else {"market": [], "stocks": []})
    memory = build_memory_block(int(profile["id"]), acct["positions"],
                                account_id=int(profile["account_id"]))
    # 编号决策协议（系统闸门已判定，模型只回答 [你] 的闸门）
    protocol_block = {}
    try:
        from . import protocol as protocol_mod
        latest = ""
        try:
            import sqlite3 as _sq
            from ..api.paths import KLINE_DB as _KDB
            _c = _sq.connect(str(_KDB))
            latest = str(_c.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0] or "")
            _c.close()
        except Exception:
            latest = ""
        protocol_block = protocol_mod.build_gates(
            int(profile["id"]), int(profile["account_id"]),
            str((profile.get("meta") or {}).get("as_of") or __import__("datetime").date.today().isoformat()),
            positions=acct["positions"], account=acct["summary"],
            regime=(market or {}).get("regime") if isinstance(market, dict) else {},
            data_latest=latest)
    except Exception as _e:
        protocol_block = {}
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
        "protocol": protocol_block,
        "prices": acct["prices"],
    }
